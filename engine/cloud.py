"""Daily cloud run for «دقيقة عقار» (GitHub Actions, see .github/workflows/daily.yml).

Steps, each logged to logs/ops.jsonl and reflected in state.json:
  1. keep READY_AHEAD episodes produced (compliance gate -> voice -> video -> QC)
  2. publish every produced video to the public GitHub release «videos» (stable URL for Buffer)
  3. schedule tomorrow's episode on TikTok via the Buffer GraphQL API (duplicate-safe)
  4. pull metrics of sent posts, write reports/ + dashboard.html

env: BUFFER_API_KEY, GITHUB_REPOSITORY, GH_TOKEN (for `gh release upload`), AQAR_VIDEOS_DIR
Exit code 1 if any step failed (GitHub then e-mails the repo owner).
"""
import json, os, pathlib, subprocess, sys
from datetime import datetime, timedelta, timezone

sys.stdout.reconfigure(encoding="utf-8")
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
import compliance  # noqa: E402
import state       # noqa: E402
import ops         # noqa: E402

import requests

ROOT = state.ROOT
CFG = json.loads((ROOT / "config.json").read_text(encoding="utf-8"))
VIDEOS = pathlib.Path(os.environ.get("AQAR_VIDEOS_DIR", ROOT / "out"))
RIYADH = timezone(timedelta(hours=3))
REPO = os.environ.get("GITHUB_REPOSITORY", "")
RELEASE = "videos"
CHANNEL = CFG["buffer"]["channels"]["tiktok"]
ORG = CFG["buffer"]["organization_id"]
failures = []


def fail(step, ep_id, err):
    failures.append(f"{step} #{ep_id}: {err}")
    state.log(f"{step}_failed", id=ep_id, error=str(err)[:300])
    print(f"FAIL {step} #{ep_id}: {err}")


# ------------------------------------------------------------------ Buffer
def gql(query, variables=None):
    r = requests.post("https://api.buffer.com", timeout=60,
                      headers={"Authorization": f"Bearer {os.environ['BUFFER_API_KEY']}"},
                      json={"query": query, "variables": variables or {}})
    r.raise_for_status()
    j = r.json()
    if j.get("errors"):
        raise RuntimeError(j["errors"][0].get("message"))
    return j["data"]


def channel_posts(status, start, end, metrics=False):
    q = """query($input: PostsInput!) { posts(first: 50, input: $input) { edges { node {
             id status dueAt sentAt text assets { source } %s } } } }""" % (
        "metrics { type value }" if metrics else "")
    d = gql(q, {"input": {"organizationId": ORG, "filter": {
        "channelIds": [CHANNEL["id"]], "status": status,
        "dueAt": {"start": start.isoformat(), "end": end.isoformat()}}}})
    return [e["node"] for e in (d["posts"]["edges"] or [])]


def create_post(ep, due):
    q = """mutation($input: CreatePostInput!) { createPost(input: $input) {
             ... on PostActionSuccess { post { id dueAt } }
             ... on MutationError { message } } }"""
    d = gql(q, {"input": {
        "channelId": CHANNEL["id"], "schedulingType": "automatic", "mode": "customScheduled",
        "dueAt": due.isoformat(), "text": ep["caption"],
        "assets": [{"video": {"url": ep["video_url"], "metadata": {"title": pathlib.Path(ep["video_file"]).stem}}}],
        "metadata": {"tiktok": {"isAiGenerated": True}}}})["createPost"]
    if "post" not in d:
        raise RuntimeError(d.get("message", "createPost failed"))
    return d["post"]["id"]


# ------------------------------------------------------------------ steps
def produce(ep_id, force=False):
    cmd = [sys.executable, str(ROOT / "engine" / "produce.py"), str(ep_id)] + (["--force"] if force else [])
    r = subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8")
    line = (r.stdout.strip().splitlines() or ["{}"])[-1]
    try:
        return json.loads(line)
    except ValueError:
        return {"ok": False, "error": (r.stderr or r.stdout)[-300:]}


def step_produce():
    ready = [e for e in state.all_episodes() if e.get("status") == "منتج" and not e.get("posts")]
    for e in state.all_episodes():
        if len(ready) >= ops.READY_AHEAD:
            break
        if e.get("status", "جاهز") != "جاهز":
            continue
        res = produce(e["id"])
        if res.get("ok"):
            ready.append(e)
            print(f"produced #{e['id']} {res.get('duration')}s")
        elif res.get("blocked"):
            print(f"blocked #{e['id']}: {res['blocked']}")
        else:
            fail("produce", e["id"], res.get("error"))


def step_publish_files():
    """Every produced-but-unscheduled episode needs a public URL; re-render if this runner lacks the file."""
    for e in state.all_episodes():
        if e.get("status") != "منتج" or e.get("video_url"):
            continue
        f = VIDEOS / (e.get("video_file") or f"aqar_{e['id']:02d}_{e['slug']}.mp4")
        if not f.exists():
            res = produce(e["id"], force=True)
            if not res.get("ok"):
                fail("produce", e["id"], res.get("error") or res.get("blocked")); continue
        r = subprocess.run(["gh", "release", "upload", RELEASE, str(f), "--clobber", "-R", REPO],
                           capture_output=True, text=True)
        if r.returncode != 0:
            fail("upload", e["id"], r.stderr.strip()); continue
        url = f"https://github.com/{REPO}/releases/download/{RELEASE}/{f.name}"
        head = requests.head(url, allow_redirects=True, timeout=60)
        if head.status_code != 200:
            fail("upload", e["id"], f"public URL returned {head.status_code}"); continue
        state.update(e["id"], video_url=url)
        state.log("uploaded", id=e["id"], url=url)


def step_schedule():
    if not CFG["buffer"]["live"]:
        print("live=false: not scheduling"); return
    tomorrow = (datetime.now(RIYADH) + timedelta(days=1)).date()
    hh, mm = map(int, CHANNEL["time"].split(":"))
    due = datetime(tomorrow.year, tomorrow.month, tomorrow.day, hh, mm, tzinfo=RIYADH)
    day0 = datetime(tomorrow.year, tomorrow.month, tomorrow.day, tzinfo=RIYADH)
    existing = channel_posts(["scheduled", "sending", "sent"], day0, day0 + timedelta(days=1))
    if existing:
        print(f"{tomorrow} already has a post on Buffer ({existing[0]['id']})"); return
    cand = [e for e in state.all_episodes() if e.get("status") == "منتج" and not e.get("posts") and e.get("video_url")]
    for ep in cand:
        blocks = compliance.blocked(compliance.check(ep))
        if blocks:   # a fact may have expired since production
            state.update(ep["id"], status="محجوب", compliance=blocks)
            state.log("compliance_block", id=ep["id"], reasons=blocks); continue
        try:
            pid = create_post(ep, due)
        except Exception as ex:
            fail("schedule", ep["id"], ex); return
        state.update(ep["id"], status="مجدول", posts={"tiktok": {"post_id": pid, "due": due.astimezone(timezone.utc).isoformat()}})
        state.log("scheduled", id=ep["id"], channel="tiktok", post_id=pid, due=due.isoformat())
        print(f"scheduled #{ep['id']} for {due.isoformat()}"); return
    fail("schedule", 0, "no produced episode with a public URL is available")


def step_metrics():
    now = datetime.now(RIYADH)
    by_post = {p["tiktok"]["post_id"]: e for e in state.all_episodes() for p in [e.get("posts") or {}] if "tiktok" in p}
    for p in channel_posts(["sent", "error"], now - timedelta(days=14), now + timedelta(days=1), metrics=True):
        e = by_post.get(p["id"])
        if not e:
            continue
        if p["status"] == "error":
            fail("publish", e["id"], "Buffer reported a publishing error"); continue
        m = {x["type"]: x["value"] for x in (p.get("metrics") or [])}
        state.update(e["id"], status="منشور", metrics={"tiktok": {k: m.get(k) for k in ("views", "likes", "comments", "shares")}})


def main():
    VIDEOS.mkdir(parents=True, exist_ok=True)
    for step in (step_produce, step_publish_files, step_schedule, step_metrics):
        try:
            step()
        except Exception as ex:
            fail(step.__name__, 0, ex)
    ops.cmd_report()
    if failures:
        print("\n".join(failures)); sys.exit(1)


if __name__ == "__main__":
    main()
