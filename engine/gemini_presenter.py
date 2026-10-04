"""Generate the presenter clip library with Gemini (Veo image-to-video) from assets/presenter.jpg.

Runs only when GEMINI_API_KEY is set (Google AI Studio key with Veo access / billing).
Each clip: ~8 s, 9:16, the presenter in a calm real-estate office set, natural gestures,
mouth closed/neutral (narration is added by produce.py, so no lip-sync mismatch).
Clips land in assets/presenter/clip_XX.mp4; produce.py picks one at random per episode.

usage:
  python engine/gemini_presenter.py            # fill the library up to gemini.clips_wanted
  python engine/gemini_presenter.py --check    # verify the key and list models with "veo"
"""
import sys as _sys
_sys.stdout.reconfigure(encoding="utf-8")
import base64, json, os, pathlib, sys, time

import requests

ROOT = pathlib.Path(__file__).resolve().parent.parent
CFG = json.loads((ROOT / "config.json").read_text(encoding="utf-8"))
G = CFG["gemini"]
API = "https://generativelanguage.googleapis.com/v1beta"
OUT = ROOT / "assets" / "presenter"

SCENES = [
    "a modern Riyadh real-estate consultancy office, warm daylight, city skyline through the window behind him",
    "a calm studio set with architectural models of residential towers on the desk, soft gold accent lights",
    "a bright meeting room with a wall map of a city master plan, soft focus background",
    "a minimalist office with bookshelves of legal volumes and a small plant, warm lighting",
    "standing beside a large window overlooking a modern residential district at golden hour",
    "a professional broadcast desk with a subtle gold and navy backdrop",
]
PROMPT = ("Vertical 9:16 video. The man in the reference image, same face, same red-and-white shemagh, black "
          "agal and white thobe, is a calm professional real-estate presenter in {scene}. Medium close-up, "
          "chest up, centered, facing camera. He listens attentively and makes small natural hand gestures and "
          "slight nods; mouth closed or neutral, not speaking. Steady camera with very slow push-in. "
          "Photorealistic, high detail, soft cinematic lighting. No text, no captions, no logos, no music.")


def key():
    k = os.environ.get(G["api_key_env"])
    if not k:
        sys.exit("NO_KEY: GEMINI_API_KEY غير موجود — المكتبة تستخدم الصورة الثابتة حتى يُضاف المفتاح")
    return k


def check():
    r = requests.get(f"{API}/models", params={"key": key(), "pageSize": 200}, timeout=60)
    r.raise_for_status()
    veo = [m["name"] for m in r.json().get("models", []) if "veo" in m["name"]]
    print(json.dumps({"ok": True, "veo_models": veo, "configured": G["veo_model"]}, ensure_ascii=False))


def generate(scene, out_path):
    k = key()
    img = (ROOT / "assets" / "presenter.jpg").read_bytes()
    body = {"instances": [{"prompt": PROMPT.format(scene=scene),
                           "image": {"bytesBase64Encoded": base64.b64encode(img).decode(), "mimeType": "image/jpeg"}}],
            "parameters": {"aspectRatio": G["aspect_ratio"], "personGeneration": "allow_adult"}}
    r = requests.post(f"{API}/models/{G['veo_model']}:predictLongRunning", headers={"x-goog-api-key": k},
                      json=body, timeout=120)
    if r.status_code != 200:
        raise RuntimeError(f"VEO_START {r.status_code}: {r.text[:300]}")
    op = r.json()["name"]
    for _ in range(90):                       # up to ~15 min
        time.sleep(10)
        s = requests.get(f"{API}/{op}", headers={"x-goog-api-key": k}, timeout=60).json()
        if s.get("done"):
            if "error" in s:
                raise RuntimeError(f"VEO_ERROR: {s['error']}")
            samples = s["response"]["generateVideoResponse"]["generatedSamples"]
            uri = samples[0]["video"]["uri"]
            v = requests.get(uri, headers={"x-goog-api-key": k}, timeout=300, allow_redirects=True)
            v.raise_for_status()
            out_path.write_bytes(v.content)
            return
    raise RuntimeError("VEO_TIMEOUT")


def main():
    if "--check" in sys.argv:
        check(); return
    OUT.mkdir(parents=True, exist_ok=True)
    have = sorted(OUT.glob("clip_*.mp4"))
    made = []
    for i in range(len(have), G["clips_wanted"]):
        path = OUT / f"clip_{i + 1:02d}.mp4"
        generate(SCENES[i % len(SCENES)], path)
        made.append(path.name)
    print(json.dumps({"ok": True, "made": made, "library": len(list(OUT.glob('clip_*.mp4')))}, ensure_ascii=False))


if __name__ == "__main__":
    main()
