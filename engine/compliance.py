"""Automated legal/content gate for «دقيقة عقار».

An episode is produced only if check(ep) returns no BLOCK findings.
  BLOCK — the episode must not be produced or published.
  WARN  — produced, but listed in the daily report for the next content review.

usage:
  python engine/compliance.py          # check every episode in content/facts.json
  python engine/compliance.py 7        # check one episode
"""
import sys as _sys
_sys.stdout.reconfigure(encoding="utf-8")
import json, pathlib, re, sys
from datetime import date
from urllib.parse import urlparse

ROOT = pathlib.Path(__file__).resolve().parent.parent
CFG = json.loads((ROOT / "config.json").read_text(encoding="utf-8"))
FACTS = ROOT / "content" / "facts.json"

REQUIRED = ["id", "slug", "topic", "hook", "body", "takeaway", "on_screen", "legal_basis", "sources", "review_by", "caption"]
# advice / prediction / urgency patterns beyond the exact banned list
ADVICE_RX = [r"\bننصح(ك|كم)?\b", r"\bيجب عليك (أن )?(تشتري|تبيع|تستثمر)", r"\bاستثمر(وا)? الآن\b", r"\bسترتفع\b", r"\bستنخفض\b"]
LATIN_RX = re.compile(r"[A-Za-z]")
DIGIT_RX = re.compile(r"[0-9٠-٩]")


def _norm(s):
    # strip tashkeel/tatweel so «اشترِ» and «اشتر» match the same rule
    return re.sub(r"[ً-ْـ]", "", s)


def official(url):
    host = (urlparse(url).hostname or "").lower()
    return any(host == d or host.endswith("." + d) for d in CFG["official_source_domains"])


def spoken_text(ep):
    return " ".join([ep["hook"], ep["body"], ep["takeaway"], CFG["outro_voice"]])


def check(ep, today=None):
    today = today or date.today()
    out = []
    add = lambda lvl, msg: out.append((lvl, msg))

    missing = [k for k in REQUIRED if not ep.get(k)]
    if missing:
        add("BLOCK", f"حقول ناقصة: {', '.join(missing)}")
        return out

    # 1) sourcing: at least one official, https source that was actually opened
    srcs = ep["sources"]
    if not any(s.get("url", "").startswith("https://") and official(s["url"]) for s in srcs):
        add("BLOCK", "لا يوجد مصدر رسمي (نطاق حكومي معتمد) لهذه المعلومة")
    if ep.get("confidence", "high") != "high":
        add("BLOCK", "درجة الثقة ليست عالية")

    # 2) freshness: facts past their re-verification date are stale
    try:
        if date.fromisoformat(ep["review_by"]) < today:
            add("BLOCK", f"انتهت صلاحية التحقق ({ep['review_by']}) — يلزم إعادة التحقق من المصدر")
    except ValueError:
        add("BLOCK", "تاريخ review_by غير صالح")

    # 3) prohibited claims: guarantees, investment advice, price predictions, urgency
    blob = _norm(" ".join([ep["hook"], ep["body"], ep["takeaway"], ep["caption"], " ".join(ep["on_screen"])]))
    for p in CFG["banned_phrases"]:
        if _norm(p) in blob:
            add("BLOCK", f"عبارة محظورة: «{p}»")
    for rx in ADVICE_RX:
        if re.search(rx, blob):
            add("BLOCK", f"صياغة توصية/تنبؤ: /{rx}/")

    # 4) length: the spoken script must fit one minute at the configured voice
    words = len(spoken_text(ep).split())
    if words > 135:
        add("BLOCK", f"النص المنطوق طويل ({words} كلمة) — يتجاوز الدقيقة")
    elif words > 125:
        add("WARN", f"النص المنطوق قريب من الحد ({words} كلمة)")
    if len(ep["hook"].split()) > 10:
        add("WARN", "الافتتاحية أطول من عشر كلمات")
    if len(ep["on_screen"]) > 3 or any(len(x.split()) > 7 for x in ep["on_screen"]):
        add("WARN", "نقاط الشاشة أكثر/أطول من اللازم")

    # 5) speakability: Latin letters or digits get mis-read by the Arabic voice
    sp = " ".join([ep["hook"], ep["body"], ep["takeaway"]])
    if LATIN_RX.search(sp):
        add("WARN", "حروف لاتينية في النص المنطوق")
    if DIGIT_RX.search(sp):
        add("WARN", "أرقام في النص المنطوق — يُفضّل كتابتها بالحروف")
    if len(ep["caption"]) > 280:
        add("WARN", "وصف المنشور أطول من 280 حرفًا (حد إكس)")
    return out


def blocked(findings):
    return [m for lvl, m in findings if lvl == "BLOCK"]


def main():
    data = json.loads(FACTS.read_text(encoding="utf-8"))
    eps = data["episodes"]
    if len(sys.argv) > 1:
        eps = [e for e in eps if e["id"] == int(sys.argv[1])]
    report = []
    for ep in eps:
        f = check(ep)
        report.append({"id": ep["id"], "topic": ep.get("topic"), "pass": not blocked(f),
                       "findings": [{"level": l, "msg": m} for l, m in f]})
    print(json.dumps(report, ensure_ascii=False, indent=1))
    sys.exit(0 if all(r["pass"] for r in report) else 1)


if __name__ == "__main__":
    main()
