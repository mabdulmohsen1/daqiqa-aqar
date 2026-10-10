"""Render one «دقيقة عقار» episode -> 1080x1920 MP4 (≤ 60 s) with the digital presenter.

usage:
  python engine/produce.py 3            # compliance gate -> voice -> video -> videos/aqar_03_slug.mp4
  python engine/produce.py 3 --force    # re-render even if the file already exists

Presenter: if assets/presenter/*.mp4 exist (Gemini Veo clips, see gemini_presenter.py) one is
looped inside the presenter frame; otherwise the still portrait assets/presenter.jpg is animated.
Enhancements (config.json "enhance", or AQAR_ENHANCE=1 for a test run), each falling back silently:
  voice_clone -> narration in Mahmoud's own voice (voice_clone.py, needs VOICE_SE_B64)
  lipsync     -> presenter's mouth follows the narration (lipsync.py, needs REPLICATE_API_TOKEN)
Prints one JSON line; exit code 0 = ok, 2 = blocked by compliance, 1 = technical failure.
"""
import sys as _sys
_sys.stdout.reconfigure(encoding="utf-8")
import asyncio, json, math, pathlib, random, re, subprocess, sys
from datetime import datetime, timezone

import arabic_reshaper
from bidi.algorithm import get_display
from fontTools.ttLib import TTFont
from PIL import Image, ImageDraw, ImageFilter, ImageFont
import imageio_ffmpeg
import unicodedata

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
import compliance  # noqa: E402
import state       # noqa: E402
import lipsync     # noqa: E402
import voice_clone # noqa: E402

ROOT = pathlib.Path(__file__).resolve().parent.parent
PROJECT = ROOT.parent
CFG = json.loads((ROOT / "config.json").read_text(encoding="utf-8"))
WORK = ROOT / "work"
# cloud runner sets AQAR_VIDEOS_DIR; locally the public Drive folder is used (see PLAYBOOK.md)
import os
VIDEOS = (pathlib.Path(os.environ["AQAR_VIDEOS_DIR"]) if os.environ.get("AQAR_VIDEOS_DIR")
          else PROJECT.parent / "تيك توك - دقيقة ذكاء" / "videos" / "دقيقة عقار")
FONT = str(ROOT / "engine" / "fonts" / "Cairo.ttf")
FFMPEG = imageio_ffmpeg.get_ffmpeg_exe()
W, H, FPS = 1080, 1920, 30
S = CFG["style"]

# presenter frame geometry
PX0, PY0, PS = 150, 250, 780
RADIUS = 44


def rgb(h):
    h = h.lstrip("#")
    return tuple(int(h[i:i + 2], 16) for i in (0, 2, 4))


BG_TOP, BG_BOT, GOLD, GOLD_SOFT, TEAL, WHITE, CARD_BG, CARD_TEXT = (
    rgb(S[k]) for k in ("bg_top", "bg_bottom", "gold", "gold_soft", "teal", "white", "card_bg", "card_text"))

# ------------------------------------------------------------------ Arabic text
_fonts, _CMAP = {}, set(TTFont(FONT).getBestCmap())


def font(size, weight="Bold"):
    if (size, weight) not in _fonts:
        # BASIC layout: text is already shaped + visually ordered by shape(); Pillow builds with
        # libraqm (e.g. Linux runners) would otherwise reorder it a second time and reverse it.
        f = ImageFont.truetype(FONT, size, layout_engine=ImageFont.Layout.BASIC)
        f.set_variation_by_name(weight)
        _fonts[(size, weight)] = f
    return _fonts[(size, weight)]


def shape(s):
    vis = get_display(arabic_reshaper.reshape(s))
    out = []
    for ch in vis:
        if ord(ch) in _CMAP:
            out.append(ch)
        else:
            n = unicodedata.normalize("NFKC", ch)
            out.append(n[::-1] if len(n) > 1 else n)
    return "".join(out)


def wrap(d, text, f, max_w):
    lines, cur = [], []
    for w in text.split():
        trial = " ".join(cur + [w])
        if cur and d.textlength(shape(trial), font=f) > max_w:
            lines.append(" ".join(cur)); cur = [w]
        else:
            cur.append(w)
    if cur:
        lines.append(" ".join(cur))
    return lines


def text_c(d, text, f, y, fill, cx=W // 2):
    t = shape(text)
    d.text((cx - d.textlength(t, font=f) / 2, y), t, font=f, fill=fill)


def text_r(d, text, f, y, fill, right):
    t = shape(text)
    d.text((right - d.textlength(t, font=f), y), t, font=f, fill=fill)


def words_line(d, words, f, y, colors):
    """Centered RTL line where each word may have its own colour (karaoke captions)."""
    sp = d.textlength(" ", font=f)
    widths = [d.textlength(shape(w), font=f) for w in words]
    total = sum(widths) + sp * (len(words) - 1)
    x = (W + total) / 2                       # start at the right edge, walk left
    for w, wd, c in zip(words, widths, colors):
        x -= wd
        d.text((x + 3, y + 3), shape(w), font=f, fill=(0, 0, 0))
        d.text((x, y), shape(w), font=f, fill=c)
        x -= sp


def fit(d, text, size, max_w, weight="Bold"):
    while size > 30 and d.textlength(shape(text), font=font(size, weight)) > max_w:
        size -= 2
    return font(size, weight)


# ------------------------------------------------------------------ static layers
def background():
    img = Image.new("RGB", (W, H))
    d = ImageDraw.Draw(img)
    for y in range(H):
        k = y / H
        d.line([(0, y), (W, y)], fill=tuple(int(BG_TOP[i] * (1 - k) + BG_BOT[i] * k) for i in range(3)))
    # low-contrast skyline behind the presenter frame
    sky = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    sd = ImageDraw.Draw(sky)
    rnd = random.Random(7)
    x, base = 0, PY0 + PS + 40
    while x < W:
        bw, bh = rnd.randint(60, 130), rnd.randint(120, 420)
        sd.rectangle((x, base - bh, x + bw - 8, base), fill=GOLD + (22,))
        x += bw
    img.paste(sky, (0, 0), sky)
    return img


def chrome(ep):
    img = background()
    d = ImageDraw.Draw(img)
    # header
    text_c(d, CFG["program"], font(76, "Black"), 52, GOLD)
    pill = f"المعلومة {ep['id']}  ·  {ep.get('category', '')}".strip(" ·")
    f = font(32, "SemiBold")
    tw = d.textlength(shape(pill), font=f)
    d.rounded_rectangle((W / 2 - tw / 2 - 26, 160, W / 2 + tw / 2 + 26, 212), 26, outline=GOLD, width=2)
    text_c(d, pill, f, 162, GOLD_SOFT)
    # presenter frame border + glow
    glow = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    ImageDraw.Draw(glow).rounded_rectangle((PX0 - 14, PY0 - 14, PX0 + PS + 14, PY0 + PS + 14), RADIUS + 12, fill=GOLD + (70,))
    img.paste(glow.filter(ImageFilter.GaussianBlur(18)), (0, 0), glow.filter(ImageFilter.GaussianBlur(18)))
    d = ImageDraw.Draw(img)
    d.rounded_rectangle((PX0 - 6, PY0 - 6, PX0 + PS + 6, PY0 + PS + 6), RADIUS + 6, fill=GOLD)
    # topic under the frame
    text_c(d, ep["topic"], fit(d, ep["topic"], 54, W - 120, "ExtraBold"), PY0 + PS + 26, WHITE)
    # footer: legal basis, disclaimer, AI label
    fb = font(28, "SemiBold")
    basis = "السند: " + ep["legal_basis"]
    lines = wrap(d, basis, fb, W - 120)[:2]
    y = 1712 - 40 * (len(lines) - 1)
    for ln in lines:
        text_c(d, ln, fb, y, GOLD_SOFT); y += 40
    text_c(d, CFG["disclaimer"], font(26, "Regular"), 1800, (190, 200, 210))
    text_c(d, CFG["ai_label"], font(24, "Regular"), 1840, (150, 165, 180))
    return img


def round_mask():
    m = Image.new("L", (PS, PS), 0)
    ImageDraw.Draw(m).rounded_rectangle((0, 0, PS - 1, PS - 1), RADIUS, fill=255)
    return m


# ------------------------------------------------------------------ presenter sources
class StillPresenter:
    """Animates the portrait: slow breathing zoom + gentle sway (no fake lip-sync)."""

    def __init__(self, path):
        im = Image.open(path).convert("RGB")
        w, h = im.size
        side = min(w, int(h * 0.82))
        self.src = im.crop(((w - side) // 2, int(h * 0.04), (w - side) // 2 + side, int(h * 0.04) + side))
        self.src = self.src.resize((PS + 120, PS + 120), Image.LANCZOS)

    def frame(self, t, speaking):
        z = 1.0 + 0.035 * (0.5 - 0.5 * math.cos(t * 2 * math.pi / 7.0)) + (0.012 if speaking else 0)
        cw = (PS + 120) / z
        cx = (PS + 120) / 2 + 10 * math.sin(t * 2 * math.pi / 9.0)
        cy = (PS + 120) / 2 - 6 * math.sin(t * 2 * math.pi / 5.5)
        box = (cx - cw / 2, cy - cw / 2, cx + cw / 2, cy + cw / 2)
        return self.src.crop(tuple(int(v) for v in box)).resize((PS, PS), Image.BILINEAR)

    def close(self):
        pass


class ClipPresenter:
    """Streams a Veo clip (looped) cropped to the square frame."""

    def __init__(self, path):
        vf = f"crop='min(iw,ih)':'min(iw,ih)',scale={PS}:{PS},fps={FPS}"
        self.p = subprocess.Popen([FFMPEG, "-loglevel", "error", "-stream_loop", "-1", "-i", str(path), "-an",
                                   "-vf", vf, "-f", "rawvideo", "-pix_fmt", "rgb24", "-"], stdout=subprocess.PIPE)
        self.n = PS * PS * 3

    def frame(self, t, speaking):
        buf = self.p.stdout.read(self.n)
        return Image.frombytes("RGB", (PS, PS), buf)

    def close(self):
        self.p.kill()


def presenter_clips():
    return sorted((ROOT / "assets" / "presenter").glob("*.mp4"))


def presenter():
    clips = presenter_clips()
    if clips:
        c = random.choice(clips)
        return ClipPresenter(c), c.name
    return StillPresenter(ROOT / "assets" / "presenter.jpg"), "presenter.jpg"


# ------------------------------------------------------------------ voice
def tts(text, out_mp3, rate):
    import edge_tts
    v = CFG["voice"]
    bounds = []

    async def run():
        c = edge_tts.Communicate(text, v["edge_voice"], rate=f"{rate:+d}%", pitch=v["pitch"], boundary="WordBoundary")
        with open(out_mp3, "wb") as f:
            async for ch in c.stream():
                if ch["type"] == "audio":
                    f.write(ch["data"])
                elif ch["type"] == "WordBoundary":
                    bounds.append((ch["offset"] / 1e7, (ch["offset"] + ch["duration"]) / 1e7))

    last = None
    for _ in range(3):
        try:
            bounds.clear(); asyncio.run(run())
            if bounds:
                return bounds
        except Exception as ex:  # network hiccups
            last = ex
    raise RuntimeError(f"TTS_FAILED: {last or 'no word timings'}")


def voice_fit(text, stem):
    """Speak at the calm default rate; speed up only as much as needed to stay under the limit."""
    v = CFG["voice"]
    rate = int(v["rate"].rstrip("%"))
    out = WORK / f"{stem}.mp3"
    for _ in range(4):
        b = tts(text, out, rate)
        dur = b[-1][1] + 1.2
        if dur <= CFG["target_duration_sec"] or rate >= v["max_rate_pct"]:
            break
        rate = min(v["max_rate_pct"], rate + max(3, math.ceil((dur / CFG["target_duration_sec"] - 1) * 100) + 1))
    return out, b, dur, rate


# ------------------------------------------------------------------ enhancements
def enhance_on(name):
    """config.json enhance.<name>, or AQAR_ENHANCE=1 to force everything on for a test run."""
    return os.environ.get("AQAR_ENHANCE") == "1" or CFG.get("enhance", {}).get(name, False)


def warn(ep_id, what, err):
    print(f"WARNING {what}: {err}")
    state.log("enhance_fallback", id=ep_id, step=what, error=str(err)[:300])


def own_voice(ep_id, edge_mp3, dur, stem):
    """Edge narration -> Mahmoud's timbre, loudness-normalised and padded to the video length."""
    if not enhance_on("voice_clone"):
        return edge_mp3, "edge"
    if not voice_clone.available():
        warn(ep_id, "voice_clone", "VOICE_SE_B64 missing"); return edge_mp3, "edge"
    try:
        raw = WORK / f"{stem}_mahmoud_raw.wav"
        out = WORK / f"{stem}_mahmoud.wav"
        voice_clone.convert(edge_mp3, raw)
        subprocess.run([FFMPEG, "-y", "-loglevel", "error", "-i", str(raw), "-af",
                        f"loudnorm=I=-16:TP=-1.5:LRA=11,apad", "-t", f"{dur:.2f}", "-ar", "44100", "-ac", "1",
                        str(out)], check=True)
        if abs(lipsync.duration(out) - dur) > 0.3:
            raise RuntimeError(f"voice length {lipsync.duration(out):.2f}s vs {dur:.2f}s")
        return out, "mahmoud"
    except Exception as ex:
        warn(ep_id, "voice_clone", ex); return edge_mp3, "edge"


def synced_presenter(ep_id, audio, dur, stem):
    """Lip-synced face track, or None (caller falls back to the plain clip)."""
    if not enhance_on("lipsync"):
        return None, {}
    clips = presenter_clips()
    if not lipsync.available() or not clips:
        warn(ep_id, "lipsync", "REPLICATE_API_TOKEN missing" if clips else "no presenter clips"); return None, {}
    padded = WORK / f"{stem}_lipsync_audio.wav"
    subprocess.run([FFMPEG, "-y", "-loglevel", "error", "-i", str(audio), "-af", "apad", "-t", f"{dur:.2f}",
                    "-ar", "16000", "-ac", "1", str(padded)], check=True)
    random.Random(ep_id).shuffle(clips)
    try:
        path, info = lipsync.sync(clips, padded, dur, stem)
    except Exception as ex:
        path, info = None, {"lipsync": "failed", "error": str(ex)[:300]}
    if path is None:
        warn(ep_id, "lipsync", info.get("error"))
    return path, info


# ------------------------------------------------------------------ render
def render(ep, out_path):
    WORK.mkdir(exist_ok=True)
    parts = [("hook", ep["hook"]), ("body", ep["body"]), ("takeaway", ep["takeaway"]), ("outro", CFG["outro_voice"])]
    words, kinds = [], []
    for k, s in parts:
        for w in s.split():
            words.append(w); kinds.append(k)
    text = " ".join(s for _, s in parts)
    stem = f"aqar{ep['id']:02d}"
    audio, bounds, dur, rate = voice_fit(text, stem)
    if dur > CFG["max_duration_sec"]:
        raise RuntimeError(f"TOO_LONG: {dur:.1f}s > {CFG['max_duration_sec']}s even at {rate:+d}%")
    audio, voice_used = own_voice(ep["id"], audio, dur, stem)
    synced, ls_info = synced_presenter(ep["id"], audio, dur, stem)

    # map voice word boundaries onto our words (punctuation-only tokens get no boundary)
    times, bi = [], 0
    for w in words:
        if re.search(r"\w", w) and bi < len(bounds):
            times.append(bounds[bi]); bi += 1
        else:
            times.append(times[-1] if times else (0.0, 0.3))
    first = {}
    for k, t in zip(kinds, times):
        first.setdefault(k, t[0])

    # caption chunks of ≤4 words that never cross a part boundary
    chunks, cur = [], []
    for i, w in enumerate(words):
        if cur and (len(cur) == 4 or kinds[cur[-1]] != kinds[i] or len(" ".join(words[j] for j in cur + [i])) > 28):
            chunks.append(cur); cur = []
        cur.append(i)
    chunks.append(cur)

    body_t0, body_t1 = first["body"], first["takeaway"]
    pts = ep["on_screen"][:3]

    def state_at(t):
        mode = "hook"
        for k in ("body", "takeaway", "outro"):
            if t >= first[k] - 0.1:
                mode = k
        ci = None
        for n, c in enumerate(chunks):
            start = times[c[0]][0] - 0.05
            end = times[chunks[n + 1][0]][0] - 0.05 if n + 1 < len(chunks) else dur
            if start <= t < end:
                ci = n
        cw = None
        if ci is not None:
            cw = max((j for j, wi in enumerate(chunks[ci]) if times[wi][0] <= t + 0.02), default=0)
        shown = 0
        if mode == "body":
            shown = min(len(pts), 1 + int((t - body_t0) / max(1.0, (body_t1 - body_t0) / len(pts))))
        elif mode in ("takeaway", "outro"):
            shown = len(pts)
        speaking = any(a - 0.05 <= t <= b + 0.1 for a, b in times[max(0, (ci or 0) * 4 - 8):])
        return (mode, ci, cw, shown), speaking

    base = chrome(ep)
    mask = round_mask()

    def overlay(st):
        mode, ci, cw, shown = st
        img = base.copy()
        d = ImageDraw.Draw(img)
        if ci is not None:
            ws = [words[i] for i in chunks[ci]]
            cols = [GOLD if j == cw else WHITE for j in range(len(ws))]
            words_line(d, ws, fit(d, " ".join(ws), 66, W - 120), PY0 + PS + 110, cols)
        top = 1300
        if mode == "hook":
            f = font(58, "Black")
            lines = wrap(d, ep["hook"], f, W - 220)
            hgt = 70 * len(lines) + 60
            d.rounded_rectangle((90, top, W - 90, top + hgt), 34, fill=GOLD)
            y = top + 28
            for ln in lines:
                text_c(d, ln, f, y, CARD_TEXT); y += 70
        if mode == "body":
            f = font(42, "Bold")
            y = top
            for p in pts[:shown]:
                d.rounded_rectangle((90, y, W - 90, y + 96), 26, fill=(18, 50, 68), outline=TEAL, width=3)
                d.ellipse((W - 150, y + 30, W - 114, y + 66), fill=TEAL)
                text_r(d, p, fit(d, p, 42, W - 300), y + 18, WHITE, W - 170)
                y += 116
        if mode == "takeaway":
            f = font(46, "ExtraBold")
            lines = wrap(d, ep["takeaway"], f, W - 240)
            hgt = 66 * len(lines) + 120
            d.rounded_rectangle((90, top, W - 90, top + hgt), 34, fill=GOLD)
            text_c(d, "الخلاصة", font(34, "Black"), top + 18, CARD_TEXT)
            y = top + 76
            for ln in lines:
                text_c(d, ln, f, y, CARD_TEXT); y += 66
        if mode == "outro":
            d.rounded_rectangle((90, top, W - 90, top + 210), 34, outline=GOLD, width=4)
            text_c(d, CFG["program"], font(64, "Black"), top + 30, GOLD)
            text_c(d, "معلومة عقارية موثّقة كل يوم", font(40, "Bold"), top + 120, WHITE)
        return img

    pres, pres_name = (ClipPresenter(synced), "lipsync:" + synced.name) if synced else presenter()
    tmp = WORK / f"aqar{ep['id']:02d}_tmp.mp4"
    cmd = [FFMPEG, "-y", "-loglevel", "error", "-f", "rawvideo", "-pix_fmt", "rgb24", "-s", f"{W}x{H}", "-r", str(FPS),
           "-i", "-", "-i", str(audio), "-c:v", "libx264", "-preset", "medium", "-crf", "20", "-pix_fmt", "yuv420p",
           "-af", "apad", "-t", f"{dur:.2f}", "-c:a", "aac", "-b:a", "160k", "-ar", "44100",
           "-movflags", "+faststart", str(tmp)]
    p = subprocess.Popen(cmd, stdin=subprocess.PIPE)
    cache, n = {}, int(dur * FPS)
    fade_in, fade_out = int(0.35 * FPS), n - int(0.6 * FPS)
    black = Image.new("RGB", (W, H), (0, 0, 0))
    try:
        for i in range(n):
            t = i / FPS
            st, speaking = state_at(t)
            if st not in cache:
                if len(cache) > 6:
                    cache.clear()
                cache[st] = overlay(st)
            img = cache[st].copy()
            img.paste(pres.frame(t, speaking), (PX0, PY0), mask)
            ImageDraw.Draw(img).rectangle((0, H - 12, int(W * t / dur), H), fill=GOLD)
            if i >= fade_out:   # no fade-in: the first frame is the TikTok hook/thumbnail
                img = Image.blend(img, black, (i - fade_out) / (n - fade_out) * 0.7)
            p.stdin.write(img.tobytes())
    finally:
        pres.close()
        p.stdin.close()
    if p.wait() != 0:
        raise RuntimeError("FFMPEG_FAILED")
    out_path.parent.mkdir(parents=True, exist_ok=True)
    tmp.replace(out_path)
    return {"duration": round(dur, 1), "rate": rate, "presenter": pres_name, "voice": voice_used,
            "lipsync": ls_info.get("lipsync", "off")}


def probe(path):
    """Independent post-render check: real duration, video + audio streams present."""
    r = subprocess.run([FFMPEG, "-i", str(path)], capture_output=True, text=True, encoding="utf-8", errors="replace")
    m = re.search(r"Duration: (\d+):(\d+):([\d.]+)", r.stderr)
    dur = int(m[1]) * 3600 + int(m[2]) * 60 + float(m[3]) if m else 0
    return {"duration": round(dur, 2), "video": "Video: h264" in r.stderr and "1080x1920" in r.stderr,
            "audio": "Audio: aac" in r.stderr}


def main():
    ep_id, force = int(sys.argv[1]), "--force" in sys.argv
    ep = state.episode(ep_id)
    findings = compliance.check(ep)
    blocks = compliance.blocked(findings)
    if blocks:
        state.update(ep_id, status="محجوب", compliance=blocks)
        state.log("compliance_block", id=ep_id, reasons=blocks)
        print(json.dumps({"ok": False, "blocked": blocks}, ensure_ascii=False)); sys.exit(2)
    out = VIDEOS / f"aqar_{ep_id:02d}_{ep['slug']}.mp4"
    if out.exists() and not force:
        print(json.dumps({"ok": True, "file": str(out), "skipped": "exists"}, ensure_ascii=False)); return
    try:
        info = render(ep, out)
        pr = probe(out)
        if not (pr["video"] and pr["audio"] and 5 < pr["duration"] <= CFG["max_duration_sec"] + 0.5):
            raise RuntimeError(f"QC_FAILED {pr}")
    except Exception as ex:
        state.update(ep_id, status="فشل الإنتاج", error=str(ex)[:300])
        state.log("produce_failed", id=ep_id, error=str(ex)[:300])
        print(json.dumps({"ok": False, "error": str(ex)[:300]}, ensure_ascii=False)); sys.exit(1)
    warns = [m for l, m in findings if l == "WARN"]
    state.update(ep_id, status="منتج", video_file=out.name, duration_sec=pr["duration"], voice_rate=info["rate"],
                 presenter=info["presenter"], voice=info["voice"], lipsync=info["lipsync"], warnings=warns, error=None,
                 produced_at=datetime.now(timezone.utc).isoformat(timespec="seconds"))
    state.log("produced", id=ep_id, file=out.name, duration=pr["duration"], presenter=info["presenter"])
    print(json.dumps({"ok": True, "file": str(out), **info, "qc": pr, "warnings": warns}, ensure_ascii=False))


if __name__ == "__main__":
    main()
