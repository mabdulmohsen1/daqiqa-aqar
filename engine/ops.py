"""Daily operations for «دقيقة عقار» (called by the scheduled task, see PLAYBOOK.md).

  python engine/ops.py plan                 # what to publish tomorrow: episode, file, caption, slots per channel
  python engine/ops.py produce-next         # produce the next episode(s) so ≥2 videos are ready ahead
  python engine/ops.py set ID key=value ... # record runtime facts (drive_id, post ids, status...)
  python engine/ops.py posted ID CHANNEL POST_ID DUE_ISO
  python engine/ops.py metrics ID CHANNEL views=.. likes=.. comments=.. shares=..
  python engine/ops.py report               # writes reports/YYYY-MM-DD.md + dashboard.html, prints summary
  python engine/ops.py status
"""
import sys as _sys
_sys.stdout.reconfigure(encoding="utf-8")
import html, json, pathlib, subprocess, sys
from collections import Counter
from datetime import datetime, timedelta, timezone

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
import compliance  # noqa: E402
import state       # noqa: E402

ROOT = state.ROOT
CFG = json.loads((ROOT / "config.json").read_text(encoding="utf-8"))
RIYADH = timezone(timedelta(hours=3))
READY_AHEAD = 2


def now_r():
    return datetime.now(RIYADH)


def parse_val(v):
    if v in ("null", "none", ""):
        return None
    try:
        return json.loads(v)
    except ValueError:
        return v


def produce(ep_id):
    r = subprocess.run([sys.executable, str(ROOT / "engine" / "produce.py"), str(ep_id)],
                       capture_output=True, text=True, encoding="utf-8")
    line = (r.stdout.strip().splitlines() or ["{}"])[-1]
    try:
        return json.loads(line)
    except ValueError:
        return {"ok": False, "error": (r.stderr or r.stdout)[-300:]}


def cmd_produce_next():
    eps = state.all_episodes()
    ready = [e for e in eps if e.get("status") == "منتج" and not e.get("posts")]
    results = []
    for e in eps:
        if len(ready) >= READY_AHEAD:
            break
        if e.get("status", "جاهز") != "جاهز":
            continue
        res = produce(e["id"])
        results.append({"id": e["id"], **res})
        if res.get("ok"):
            ready.append(e)
    print(json.dumps({"ready_ahead": len(ready), "results": results}, ensure_ascii=False, indent=1))


def cmd_plan():
    """Tomorrow's publication: earliest produced, unposted episode + one slot per channel."""
    tomorrow = (now_r() + timedelta(days=1)).date()
    eps = state.all_episodes()
    taken = {p["due"][:10] for e in eps for p in (e.get("posts") or {}).values()}
    if tomorrow.isoformat() in taken:
        print(json.dumps({"action": "none", "reason": f"{tomorrow} مجدول مسبقًا"}, ensure_ascii=False)); return
    cand = [e for e in eps if e.get("status") == "منتج" and not e.get("posts")]
    if not cand:
        print(json.dumps({"action": "none", "reason": "لا توجد حلقة منتجة جاهزة — شغّل produce-next"}, ensure_ascii=False)); return
    ep = cand[0]
    # re-run the gate at publish time (a fact may have expired since production)
    blocks = compliance.blocked(compliance.check(ep))
    if blocks:
        state.update(ep["id"], status="محجوب", compliance=blocks)
        print(json.dumps({"action": "blocked", "id": ep["id"], "reasons": blocks}, ensure_ascii=False)); return
    slots = {}
    for name, ch in CFG["buffer"]["channels"].items():
        hh, mm = map(int, ch["time"].split(":"))
        due = datetime(tomorrow.year, tomorrow.month, tomorrow.day, hh, mm, tzinfo=RIYADH)
        slots[name] = {"channel_id": ch["id"], "dueAt": due.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")}
    print(json.dumps({"action": "schedule", "live": CFG["buffer"]["live"], "id": ep["id"], "topic": ep["topic"],
                      "video_file": ep["video_file"], "drive_id": ep.get("drive_id"),
                      "text": ep["caption"], "slots": slots}, ensure_ascii=False, indent=1))


def cmd_set(ep_id, pairs):
    kw = {k: parse_val(v) for k, v in (p.split("=", 1) for p in pairs)}
    print(json.dumps(state.update(int(ep_id), **kw), ensure_ascii=False))
    state.log("set", id=int(ep_id), **kw)


def cmd_posted(ep_id, channel, post_id, due):
    ep = state.episode(int(ep_id))
    posts = ep.get("posts") or {}
    posts[channel] = {"post_id": post_id, "due": due}
    status = "مجدول" if len(posts) >= len(CFG["buffer"]["channels"]) else ep.get("status")
    state.update(int(ep_id), posts=posts, status=status)
    state.log("scheduled", id=int(ep_id), channel=channel, post_id=post_id, due=due)
    print(json.dumps({"ok": True, "posts": posts}, ensure_ascii=False))


def cmd_metrics(ep_id, channel, pairs):
    ep = state.episode(int(ep_id))
    m = ep.get("metrics") or {}
    m[channel] = {k: parse_val(v) for k, v in (p.split("=", 1) for p in pairs)}
    m[channel]["at"] = now_r().isoformat(timespec="minutes")
    state.update(int(ep_id), metrics=m)
    print(json.dumps({"ok": True}, ensure_ascii=False))


def summary():
    eps = state.all_episodes()
    log = state.read_log()
    week_ago = (datetime.now(timezone.utc) - timedelta(days=7)).isoformat()
    recent = [l for l in log if l["at"] >= week_ago]
    ev = Counter(l["event"] for l in recent)
    st = Counter(e.get("status", "جاهز") for e in eps)
    views = sum((m.get("views") or 0) for e in eps for m in (e.get("metrics") or {}).values())
    produced = [e for e in eps if e.get("duration_sec")]
    expiring = [e for e in eps if e.get("review_by", "9999") <= (now_r() + timedelta(days=14)).date().isoformat()]
    return {
        "at": now_r().isoformat(timespec="minutes"),
        "library": len(eps), "status": dict(st),
        "unpublished_ready": sum(1 for e in eps if e.get("status") == "منتج" and not e.get("posts")),
        "days_of_content_left": st.get("جاهز", 0) + st.get("منتج", 0),
        "week": {"produced": ev.get("produced", 0), "scheduled": ev.get("scheduled", 0),
                 "compliance_blocks": ev.get("compliance_block", 0), "failures": ev.get("produce_failed", 0) + ev.get("publish_failed", 0)},
        "avg_duration": round(sum(e["duration_sec"] for e in produced) / len(produced), 1) if produced else None,
        "max_duration": max((e["duration_sec"] for e in produced), default=None),
        "warnings_open": sum(len(e.get("warnings") or []) for e in eps if e.get("status") in ("منتج", "مجدول")),
        "total_views": views,
        "facts_expiring_14d": [e["id"] for e in expiring],
        "live": CFG["buffer"]["live"],
    }


def cmd_report():
    s = summary()
    eps = state.all_episodes()
    rep = ROOT / "reports"
    rep.mkdir(exist_ok=True)
    day = now_r().date().isoformat()
    md = [f"# تقرير دقيقة عقار — {day}", "",
          f"- المكتبة: {s['library']} معلومة · متبقٍّ للنشر: {s['days_of_content_left']} يومًا",
          f"- هذا الأسبوع: أُنتج {s['week']['produced']} · جُدول {s['week']['scheduled']} · حُجب نظاميًا {s['week']['compliance_blocks']} · أعطال {s['week']['failures']}",
          f"- متوسط المدة: {s['avg_duration']} ث · الأقصى: {s['max_duration']} ث (الحد 60)",
          f"- إجمالي المشاهدات المسجلة: {s['total_views']}",
          f"- معلومات تنتهي صلاحية تحققها خلال 14 يومًا: {s['facts_expiring_14d'] or 'لا يوجد'}",
          f"- النشر الفعلي: {'مفعّل' if s['live'] else 'متوقف بانتظار الاعتماد'}", ""]
    (rep / f"{day}.md").write_text("\n".join(md), encoding="utf-8")

    rows = []
    for e in eps:
        posts = " · ".join(f"{k}: {v['due'][:16].replace('T', ' ')}" for k, v in (e.get("posts") or {}).items())
        views = sum((m.get("views") or 0) for m in (e.get("metrics") or {}).values())
        rows.append(f"<tr><td>{e['id']}</td><td>{html.escape(e['topic'])}</td><td>{html.escape(e.get('category', ''))}</td>"
                    f"<td>{html.escape(e.get('status', 'جاهز'))}</td><td>{e.get('duration_sec') or ''}</td>"
                    f"<td>{html.escape(posts)}</td><td>{views or ''}</td><td>{e.get('review_by', '')}</td>"
                    f"<td>{html.escape('؛ '.join((e.get('compliance') or []) + (e.get('warnings') or [])))}</td></tr>")
    tiles = [("متبقٍّ للنشر (أيام)", s["days_of_content_left"]), ("جاهز مقدّمًا", s["unpublished_ready"]),
             ("أُنتج هذا الأسبوع", s["week"]["produced"]), ("حُجب نظاميًا", s["week"]["compliance_blocks"]),
             ("أعطال", s["week"]["failures"]), ("أقصى مدة (ث)", s["max_duration"] or "—"), ("المشاهدات", s["total_views"])]
    page = f"""<!doctype html><html lang="ar" dir="rtl"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1"><title>لوحة دقيقة عقار</title>
<style>body{{font-family:Tahoma,Arial;background:#06141D;color:#eef;margin:0;padding:20px}}
h1{{color:#D4A84B;margin:0 0 4px}}.sub{{color:#9ab;margin-bottom:18px}}
.tiles{{display:flex;flex-wrap:wrap;gap:10px;margin-bottom:18px}}.t{{background:#0E2A3B;border:1px solid #D4A84B55;border-radius:12px;padding:12px 16px;min-width:130px}}
.t b{{display:block;font-size:26px;color:#F1D9A0}}table{{width:100%;border-collapse:collapse;font-size:14px}}
td,th{{border-bottom:1px solid #1d3b4d;padding:7px;text-align:right;vertical-align:top}}th{{color:#D4A84B}}</style></head><body>
<h1>دقيقة عقار</h1><div class="sub">آخر تحديث {s['at']} · النشر {'مفعّل' if s['live'] else 'متوقف بانتظار الاعتماد'}</div>
<div class="tiles">{''.join(f'<div class="t"><b>{v}</b>{k}</div>' for k, v in tiles)}</div>
<table><tr><th>#</th><th>الموضوع</th><th>الفئة</th><th>الحالة</th><th>المدة</th><th>النشر</th><th>مشاهدات</th><th>إعادة التحقق</th><th>ملاحظات الامتثال</th></tr>
{''.join(rows)}</table></body></html>"""
    (ROOT / "dashboard.html").write_text(page, encoding="utf-8")
    print(json.dumps(s, ensure_ascii=False, indent=1))


def main():
    a = sys.argv[1:]
    if not a or a[0] == "status":
        print(json.dumps(summary(), ensure_ascii=False, indent=1))
    elif a[0] == "plan":
        cmd_plan()
    elif a[0] == "produce-next":
        cmd_produce_next()
    elif a[0] == "set":
        cmd_set(a[1], a[2:])
    elif a[0] == "posted":
        cmd_posted(*a[1:5])
    elif a[0] == "metrics":
        cmd_metrics(a[1], a[2], a[3:])
    elif a[0] == "report":
        cmd_report()
    else:
        sys.exit(__doc__)


if __name__ == "__main__":
    main()
