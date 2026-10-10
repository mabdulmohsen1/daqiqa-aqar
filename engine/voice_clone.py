"""Turn the Edge TTS narration into Mahmoud's own voice (OpenVoice V2 tone-colour converter, MIT, CPU).

Edge TTS still writes the words and the word timings (captions depend on them); the converter only
changes the timbre, frame-for-frame, so timings stay valid.

Mahmoud's voice fingerprint (a 256-number speaker embedding, never the recording itself) comes from:
  env VOICE_SE_B64          base64 of the torch-saved embedding (GitHub secret in the cloud), or
  work/voice/target_se.pth  local copy made by:  python engine/voice_clone.py make-se <sample.m4a>
The voice sample stays OFF the public repo.

usage:
  python engine/voice_clone.py make-se "<path to voice sample>"   # -> work/voice/target_se.pth + .b64
  python engine/voice_clone.py convert in.mp3 out.wav               # manual test
"""
import base64, io, os, pathlib, subprocess, sys, tempfile, types

import imageio_ffmpeg

ROOT = pathlib.Path(__file__).resolve().parent.parent
VOICE_DIR = ROOT / "work" / "voice"
LOCAL_SE = VOICE_DIR / "target_se.pth"
FFMPEG = imageio_ffmpeg.get_ffmpeg_exe()
_conv = None


def available():
    return bool(os.environ.get("VOICE_SE_B64")) or LOCAL_SE.exists()


def _converter():
    global _conv
    if _conv is None:
        # openvoice.text pulls English/Chinese text front-ends we never use: stub it out
        stub = types.ModuleType("openvoice.text")
        stub.text_to_sequence = None
        sys.modules["openvoice.text"] = stub
        from huggingface_hub import hf_hub_download
        from openvoice.api import OpenVoiceBaseClass, ToneColorConverter
        cfg = hf_hub_download("myshell-ai/OpenVoiceV2", "converter/config.json")
        ckpt = hf_hub_download("myshell-ai/OpenVoiceV2", "converter/checkpoint.pth")
        # upstream __init__ forwards enable_watermark to the base class and crashes: init by hand
        _conv = ToneColorConverter.__new__(ToneColorConverter)
        OpenVoiceBaseClass.__init__(_conv, cfg, device="cpu")
        _conv.watermark_model, _conv.version = None, getattr(_conv.hps, "_version_", "v1")
        _conv.load_ckpt(ckpt)
    return _conv


def _wav_chunks(src, tmp, sec=10):
    """Decode to 22.05 kHz mono and split into ~10 s pieces (what OpenVoice's own extractor does)."""
    sr = _converter().hps.data.sampling_rate
    pat = str(pathlib.Path(tmp) / "seg_%03d.wav")
    subprocess.run([FFMPEG, "-y", "-loglevel", "error", "-i", str(src), "-ac", "1", "-ar", str(sr),
                    "-af", "silenceremove=stop_periods=-1:stop_duration=0.4:stop_threshold=-40dB",
                    "-f", "segment", "-segment_time", str(sec), pat], check=True)
    segs = sorted(pathlib.Path(tmp).glob("seg_*.wav"))
    return [str(s) for s in segs if s.stat().st_size > sr * 2 * 3] or [str(s) for s in segs]


def embedding(src):
    with tempfile.TemporaryDirectory() as tmp:
        return _converter().extract_se(_wav_chunks(src, tmp))


def target_se():
    import torch
    b64 = os.environ.get("VOICE_SE_B64")
    raw = base64.b64decode(b64) if b64 else LOCAL_SE.read_bytes()
    return torch.load(io.BytesIO(raw), map_location="cpu")


def convert(src_audio, out_wav, tau=0.3):
    """src_audio (Edge mp3) -> out_wav in Mahmoud's voice. Returns out_wav."""
    conv = _converter()
    with tempfile.TemporaryDirectory() as tmp:
        wav = pathlib.Path(tmp) / "src.wav"
        subprocess.run([FFMPEG, "-y", "-loglevel", "error", "-i", str(src_audio), "-ac", "1",
                        "-ar", str(conv.hps.data.sampling_rate), str(wav)], check=True)
        src_se = conv.extract_se(_wav_chunks(src_audio, tmp))
        conv.convert(str(wav), src_se, target_se(), output_path=str(out_wav), tau=tau)
    return out_wav


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8")
    if sys.argv[1] == "make-se":
        import torch
        VOICE_DIR.mkdir(parents=True, exist_ok=True)
        se = embedding(sys.argv[2])
        torch.save(se.cpu(), LOCAL_SE)
        (VOICE_DIR / "target_se.b64.txt").write_text(base64.b64encode(LOCAL_SE.read_bytes()).decode())
        print(f"saved {LOCAL_SE} ({LOCAL_SE.stat().st_size} bytes) + target_se.b64.txt")
    elif sys.argv[1] == "convert":
        print(convert(sys.argv[2], sys.argv[3]))
