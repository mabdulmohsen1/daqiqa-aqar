"""Shared state for «دقيقة عقار»: content (content/facts.json, read-only here) + runtime
status (state.json) + append-only operations log (logs/ops.jsonl)."""
import json, pathlib
from datetime import datetime, timezone

ROOT = pathlib.Path(__file__).resolve().parent.parent
FACTS = ROOT / "content" / "facts.json"
STATE = ROOT / "state.json"
LOG = ROOT / "logs" / "ops.jsonl"


def _now():
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def facts():
    return json.loads(FACTS.read_text(encoding="utf-8"))["episodes"]


def load():
    return json.loads(STATE.read_text(encoding="utf-8")) if STATE.exists() else {"episodes": {}}


def save(st):
    tmp = STATE.with_suffix(".tmp")
    tmp.write_text(json.dumps(st, ensure_ascii=False, indent=2), encoding="utf-8")
    tmp.replace(STATE)


def episode(ep_id):
    """Content merged with runtime status."""
    ep = next(e for e in facts() if e["id"] == ep_id)
    return {**ep, **load()["episodes"].get(str(ep_id), {})}


def all_episodes():
    st = load()["episodes"]
    return [{**e, **st.get(str(e["id"]), {})} for e in facts()]


def update(ep_id, **kw):
    st = load()
    cur = st["episodes"].setdefault(str(ep_id), {"status": "جاهز"})
    cur.update(kw)
    cur["updated_at"] = _now()
    save(st)
    return cur


def log(event, **kw):
    LOG.parent.mkdir(exist_ok=True)
    with LOG.open("a", encoding="utf-8") as f:
        f.write(json.dumps({"at": _now(), "event": event, **kw}, ensure_ascii=False) + "\n")


def read_log():
    if not LOG.exists():
        return []
    return [json.loads(l) for l in LOG.read_text(encoding="utf-8").splitlines() if l.strip()]
