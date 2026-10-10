"""Make the presenter's mouth follow the narration (Replicate bytedance/latentsync).

build_track(): loop/chain the Veo clips into one square face video exactly as long as the audio
sync():        send video + audio to Replicate, download, QC (duration ±0.3 s, face present), cache
Any failure -> retry once -> return None so produce.py falls back to the raw clip (never blocks a post).

env: REPLICATE_API_TOKEN (GitHub secret). Cache: work/lipsync/<sha>.mp4 keyed on clip + audio bytes.
"""
import hashlib, os, pathlib, re, subprocess, time

import imageio_ffmpeg
import requests

ROOT = pathlib.Path(__file__).resolve().parent.parent
CACHE = ROOT / "work" / "lipsync"
FFMPEG = imageio_ffmpeg.get_ffmpeg_exe()
API = "https://api.replicate.com/v1"
MODEL = "bytedance/latentsync"
SIDE = 512          # face track resolution sent to the model (upscaled into the 780 px frame)


def available():
    return bool(os.environ.get("REPLICATE_API_TOKEN"))


def _h():
    return {"Authorization": f"Bearer {os.environ['REPLICATE_API_TOKEN']}"}


def duration(path):
    r = subprocess.run([FFMPEG, "-i", str(path)], capture_output=True, text=True, encoding="utf-8", errors="replace")
    m = re.search(r"Duration: (\d+):(\d+):([\d.]+)", r.stderr)
    return int(m[1]) * 3600 + int(m[2]) * 60 + float(m[3]) if m else 0.0


def build_track(clips, seconds, out):
    """Chain the clips (in order, repeating) into a silent square 25 fps video of exactly `seconds`."""
    lst = out.with_suffix(".txt")
    total, items = 0.0, []
    lens = [max(0.5, duration(c)) for c in clips]
    i = 0
    while total < seconds + 0.5:
        items.append(clips[i % len(clips)]); total += lens[i % len(clips)]; i += 1
    lst.write_text("".join(f"file '{pathlib.Path(c).resolve().as_posix()}'\n" for c in items), encoding="utf-8")
    vf = f"crop='min(iw,ih)':'min(iw,ih)',scale={SIDE}:{SIDE},fps=25"
    subprocess.run([FFMPEG, "-y", "-loglevel", "error", "-f", "concat", "-safe", "0", "-i", str(lst), "-an",
                    "-vf", vf, "-t", f"{seconds:.2f}", "-c:v", "libx264", "-crf", "18", "-pix_fmt", "yuv420p",
                    str(out)], check=True)
    return out


def _upload(path):
    with open(path, "rb") as f:
        r = requests.post(f"{API}/files", headers=_h(), timeout=300,
                          files={"content": (pathlib.Path(path).name, f, "application/octet-stream")})
    r.raise_for_status()
    return r.json()["urls"]["get"]


def _run(video, audio):
    ver = requests.get(f"{API}/models/{MODEL}", headers=_h(), timeout=60).json()["latest_version"]["id"]
    r = requests.post(f"{API}/predictions", headers=_h(), timeout=120, json={
        "version": ver, "input": {"video": _upload(video), "audio": _upload(audio), "guidance_scale": 1.5, "seed": 7}})
    r.raise_for_status()
    p = r.json()
    t0 = time.time()
    while p["status"] not in ("succeeded", "failed", "canceled"):
        if time.time() - t0 > 900:
            requests.post(f"{API}/predictions/{p['id']}/cancel", headers=_h(), timeout=30)
            raise RuntimeError("LIPSYNC_TIMEOUT")
        time.sleep(5)
        p = requests.get(f"{API}/predictions/{p['id']}", headers=_h(), timeout=60).json()
    if p["status"] != "succeeded":
        raise RuntimeError(f"LIPSYNC_{p['status'].upper()}: {str(p.get('error'))[:200]}")
    out = p["output"] if isinstance(p["output"], str) else p["output"][0]
    return requests.get(out, timeout=300).content, p.get("metrics", {}).get("predict_time")


def face_ok(path, samples=5):
    """Frontal face found in most sampled frames (OpenCV Haar cascade)."""
    import cv2
    det = cv2.CascadeClassifier(cv2.data.haarcascades + "haarcascade_frontalface_default.xml")
    cap = cv2.VideoCapture(str(path))
    n = int(cap.get(cv2.CAP_PROP_FRAME_COUNT)) or 1
    hits = 0
    for k in range(samples):
        cap.set(cv2.CAP_PROP_POS_FRAMES, int(n * (k + 0.5) / samples))
        ok, fr = cap.read()
        if ok and len(det.detectMultiScale(cv2.cvtColor(fr, cv2.COLOR_BGR2GRAY), 1.1, 5, minSize=(80, 80))):
            hits += 1
    cap.release()
    return hits >= samples - 1


def sync(clips, audio, seconds, tag):
    """-> (path to lip-synced face video | None, info dict)."""
    CACHE.mkdir(parents=True, exist_ok=True)
    key = hashlib.sha256(b"".join(pathlib.Path(c).read_bytes()[:1 << 20] for c in clips)
                         + pathlib.Path(audio).read_bytes()).hexdigest()[:16]
    out = CACHE / f"{tag}_{key}.mp4"
    if out.exists():
        return out, {"lipsync": "cached"}
    track = build_track(clips, seconds, CACHE / f"{tag}_track.mp4")
    err = None
    for attempt in (1, 2):
        try:
            data, secs = _run(track, audio)
            tmp = out.with_suffix(".part.mp4")
            tmp.write_bytes(data)
            d = duration(tmp)
            if abs(d - seconds) > 0.3:
                raise RuntimeError(f"LIPSYNC_QC duration {d:.2f}s vs audio {seconds:.2f}s")
            if not face_ok(tmp):
                raise RuntimeError("LIPSYNC_QC no face")
            tmp.replace(out)
            return out, {"lipsync": "ok", "attempts": attempt, "gpu_sec": secs}
        except Exception as ex:
            err = str(ex)[:300]
            print(f"lipsync attempt {attempt} failed: {err}")
    return None, {"lipsync": "failed", "error": err}
