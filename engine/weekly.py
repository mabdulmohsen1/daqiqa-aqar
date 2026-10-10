"""Weekly performance review for «دقيقة عقار» (GitHub Actions, see .github/workflows/weekly.yml).

Reads state.json (metrics refreshed by the daily run) and writes reports/weekly-YYYY-MM-DD.md:
  - every aired episode: hook, duration, views, avg watch, retention %, likes, shares
  - last 7 days vs the 7 days before (mean views, mean avg watch, mean retention)
  - the experiment that is currently live (top entry of CHANGELOG.md)
The weekly Claude task reads this file, decides, and applies exactly ONE change (see EXPERIMENTS.md).

usage: python engine/weekly.py [YYYY-MM-DD]   # default: today (Riyadh)
"""
import pathlib, re, sys
from datetime import date, datetime, timedelta, timezone

sys.stdout.reconfigure(encoding="utf-8")
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
import state  # noqa: E402

RIYADH = timezone(timedelta(hours=3))


def aired(e):
    due = ((e.get("posts") or {}).get("tiktok") or {}).get("due")
    return datetime.fromisoformat(due.replace("Z", "+00:00")).astimezone(RIYADH).date() if due else None


def row(e):
    m = (e.get("metrics") or {}).get("tiktok") or {}
    dur = e.get("duration_sec") or 0
    avg = m.get("avg_watch_sec")
    return {"id": e["id"], "day": aired(e), "hook": e["hook"], "dur": dur, "views": m.get("views") or 0,
            "avg": avg, "ret": round(100 * avg / dur, 1) if avg and dur else None,
            "likes": m.get("likes"), "shares": m.get("shares"), "comments": m.get("comments")}


def mean(xs):
    xs = [x for x in xs if x is not None]
    return round(sum(xs) / len(xs), 1) if xs else None


def window(rows, start, end):
    w = [r for r in rows if start <= r["day"] < end]
    return {"n": len(w), "views": mean([r["views"] for r in w]), "avg": mean([r["avg"] for r in w]),
            "ret": mean([r["ret"] for r in w])}


def current_experiment():
    cl = state.ROOT / "CHANGELOG.md"
    if not cl.exists():
        return "—"
    m = re.search(r"^## .+?(?=^## |\Z)", cl.read_text(encoding="utf-8"), re.S | re.M)
    return m.group(0).strip() if m else "—"


def main():
    today = date.fromisoformat(sys.argv[1]) if len(sys.argv) > 1 else datetime.now(RIYADH).date()
    # metrics settle ~24h after posting: score only episodes aired before today
    rows = sorted((row(e) for e in state.all_episodes() if e.get("status") == "منشور" and aired(e) and aired(e) < today),
                  key=lambda r: r["day"])
    this = window(rows, today - timedelta(days=7), today)
    prev = window(rows, today - timedelta(days=14), today - timedelta(days=7))

    f = lambda x: "—" if x is None else x

    def delta(k):
        a, b = this[k], prev[k]
        return f"{a} ({'+' if a - b >= 0 else ''}{round(100 * (a - b) / b)}%)" if a is not None and b else f"{f(a)}"

    md = [f"# المراجعة الأسبوعية — دقيقة عقار — {today}", "",
          "| المؤشر | آخر 7 أيام | الأسبوع السابق |", "|---|---|---|",
          f"| حلقات منشورة | {this['n']} | {prev['n']} |",
          f"| متوسط المشاهدات | {delta('views')} | {f(prev['views'])} |",
          f"| متوسط مدة المشاهدة (ث) | {delta('avg')} | {f(prev['avg'])} |",
          f"| نسبة الاحتفاظ (متوسط المشاهدة ÷ المدة) | {delta('ret')} | {f(prev['ret'])} |", "",
          "## كل الحلقات المنشورة", "",
          "| # | تاريخ النشر | الافتتاحية | المدة | مشاهدات | متوسط المشاهدة | احتفاظ % | إعجاب | مشاركة | تعليق |",
          "|---|---|---|---|---|---|---|---|---|---|"]
    md += [f"| {r['id']} | {r['day']} | {r['hook']} | {r['dur']} | {r['views']} | {r['avg'] if r['avg'] is not None else '—'} | "
           f"{r['ret'] if r['ret'] is not None else '—'} | {r['likes'] if r['likes'] is not None else '—'} | "
           f"{r['shares'] if r['shares'] is not None else '—'} | {r['comments'] if r['comments'] is not None else '—'} |" for r in rows]
    if rows:
        best = max((r for r in rows if r["ret"] is not None), key=lambda r: r["ret"], default=None)
        if best:
            md += ["", f"- أعلى احتفاظ: #{best['id']} «{best['hook']}» ({best['ret']}%)"]
    md += ["", "## التجربة الحالية (من CHANGELOG.md)", "", current_experiment(), ""]
    out = state.ROOT / "reports" / f"weekly-{today}.md"
    out.parent.mkdir(exist_ok=True)
    out.write_text("\n".join(md), encoding="utf-8")
    print(out)


if __name__ == "__main__":
    main()
