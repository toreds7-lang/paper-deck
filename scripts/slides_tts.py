"""Render each slide's narration script to speech with Kokoro (kokoro-onnx).

    python slides_tts.py                       # every deck in ./slides
    python slides_tts.py mini_omni
    python slides_tts.py --check               # report only, synthesise nothing
    python slides_tts.py mini_omni --only s07,s12
    python slides_tts.py --voice af_bella --speed 1.0
    python slides_tts.py --fetch-models        # download the two model files

Resumable by design, and it retries only what actually needs it: a clip is
re-rendered when it is missing, when its script changed, when the voice or speed
changed, or when the last attempt failed. Re-running the same command therefore
retries exactly the failures. The script hash is what stops stale audio
narrating a slide that has since been edited, which is the failure mode you
would otherwise never notice.

Models (~353MB, downloaded once, never in git):
    slides_assets/kokoro/kokoro-v1.0.onnx
    slides_assets/kokoro/voices-v1.0.bin
A shared copy can live at ~/.cache/paper-deck/kokoro/ and is used if present.
"""
from __future__ import annotations

import hashlib
import json
import os
import re
import sys
import time
from pathlib import Path

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

REL = "https://github.com/thewh1teagle/kokoro-onnx/releases/download/model-files-v1.1"
MODEL_URLS = {"kokoro-v1.0.onnx": f"{REL}/kokoro-v1.0.onnx",
              "voices-v1.0.bin": f"{REL}/voices-v1.0.bin"}
SHARED = Path.home() / ".cache" / "paper-deck" / "kokoro"

DEFAULT_VOICE = "af_heart"      # grade A in hexgrad/Kokoro-82M VOICES.md
DEFAULT_SPEED = 1.0

# Said aloud, these would otherwise come out as letters, symbols or silence.
# Per-deck additions go in the deck JSON's meta.pronounce, which is where to put
# a fix when a clip mispronounces something.
BASE_PRONOUNCE = {
    "LLM": "L L M", "ASR": "A S R", "TTS": "T T S", "GPU": "G P U", "CPU": "C P U",
    "WER": "word error rate", "SOTA": "state of the art", "kHz": "kilohertz",
    "tok/s": "tokens per second", "->": " to ", "→": " to ", "≈": " about ",
    "×": " by ", "%": " percent", "&": " and ",
}


def project_dir(argv: list[str]) -> Path:
    if "--dir" in argv:
        return Path(argv[argv.index("--dir") + 1]).resolve()
    return Path(os.environ.get("PAPER_DECK_DIR") or Path.cwd()).resolve()


PROJECT = Path.cwd()
DECKS_DIR = PROJECT / "slides"
OUT_ASSETS = PROJECT / "slides_assets"


def _rebind(root: Path) -> None:
    global PROJECT, DECKS_DIR, OUT_ASSETS
    PROJECT, DECKS_DIR, OUT_ASSETS = root, root / "slides", root / "slides_assets"


def all_decks() -> list[str]:
    if not DECKS_DIR.exists():
        return []
    return sorted(p.stem for p in DECKS_DIR.glob("*.json")
                  if not p.name.endswith(".scripts.json"))


def model_paths() -> tuple[Path, Path]:
    local = OUT_ASSETS / "kokoro"
    if (local / "kokoro-v1.0.onnx").exists():
        return local / "kokoro-v1.0.onnx", local / "voices-v1.0.bin"
    if (SHARED / "kokoro-v1.0.onnx").exists():
        return SHARED / "kokoro-v1.0.onnx", SHARED / "voices-v1.0.bin"
    return local / "kokoro-v1.0.onnx", local / "voices-v1.0.bin"


def fetch_models(dest: Path | None = None) -> bool:
    """Download the model files once. Atomic: .part then replace."""
    import urllib.request

    dest = dest or SHARED
    dest.mkdir(parents=True, exist_ok=True)
    for fname, url in MODEL_URLS.items():
        out = dest / fname
        if out.exists() and out.stat().st_size > 1_000_000:
            print(f"  have {fname} ({out.stat().st_size / 1e6:.0f} MB)")
            continue
        print(f"  downloading {fname} ...")
        tmp = out.with_suffix(out.suffix + ".part")
        try:
            urllib.request.urlretrieve(url, tmp)
            os.replace(tmp, out)
            print(f"  got {fname} ({out.stat().st_size / 1e6:.0f} MB)")
        except Exception as exc:
            print(f"  FAILED {fname}: {exc}\n  fetch it by hand from {url}")
            return False
    return True


def normalize(text: str, pronounce: dict) -> str:
    """Make a script safe and natural to speak."""
    t = text.strip()
    table = {**BASE_PRONOUNCE, **(pronounce or {})}
    for k in sorted(table, key=len, reverse=True):
        t = re.sub(re.escape(k), table[k], t)
    t = re.sub(r"\s+", " ", t)
    t = re.sub(r"\s+([,.;:!?])", r"\1", t)
    return t.strip()


def script_hash(text: str, voice: str, speed: float) -> str:
    return hashlib.sha1(f"{voice}|{speed}|{text}".encode("utf-8")).hexdigest()[:16]


def load_index(audio_dir: Path) -> dict:
    p = audio_dir / "manifest.json"
    if not p.exists():
        return {"clips": {}}
    try:
        d = json.loads(p.read_text(encoding="utf-8"))
        d.setdefault("clips", {})
        return d
    except Exception:
        return {"clips": {}}


def save_index(audio_dir: Path, idx: dict) -> None:
    p = audio_dir / "manifest.json"
    tmp = p.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(idx, ensure_ascii=False, indent=2), encoding="utf-8")
    os.replace(tmp, p)


def narrate(name: str, voice: str, speed: float, only: set[str] | None,
            check_only: bool) -> bool:
    deck_path = DECKS_DIR / f"{name}.json"
    if not deck_path.exists():
        print(f"[{name}] deck json not found: {deck_path}")
        return False
    deck = json.loads(deck_path.read_text(encoding="utf-8"))
    slides = deck.get("slides") or []
    pronounce = (deck.get("meta") or {}).get("pronounce") or {}

    audio_dir = OUT_ASSETS / name / "audio"
    audio_dir.mkdir(parents=True, exist_ok=True)
    idx = load_index(audio_dir)

    todo, cached = [], 0
    for s in slides:
        sid, raw = s.get("id"), (s.get("script") or "").strip()
        if not sid or not raw or (only and sid not in only):
            continue
        norm = normalize(raw, pronounce)
        h = script_hash(norm, voice, speed)
        rec = idx["clips"].get(sid)
        fresh = (rec and not rec.get("error") and rec.get("h") == h
                 and rec.get("f") and (audio_dir / rec["f"]).exists())
        if fresh and not only:
            cached += 1
            continue
        todo.append((sid, norm, h))

    if check_only:
        failed = [k for k, v in idx["clips"].items() if v.get("error")]
        print(f"[{name}] {cached} ok / {len(todo)} to render / {len(failed)} failed")
        for k in failed:
            print(f"    FAIL {k}: {idx['clips'][k]['error']}")
        return not failed and not todo

    if not todo:
        print(f"[{name}] all {cached} clips up to date")
        return True

    model, voices = model_paths()
    if not model.exists() or not voices.exists():
        print(f"[{name}] model files missing. Run:  python slides_tts.py --fetch-models")
        return False

    import soundfile as sf
    from kokoro_onnx import Kokoro

    print(f"[{name}] {cached} cached, rendering {len(todo)} with voice={voice} speed={speed}")
    kokoro = Kokoro(str(model), str(voices))
    lang = "en-gb" if voice[:1] == "b" else "en-us"

    ok = fail = 0
    for n, (sid, norm, h) in enumerate(todo, 1):
        t0 = time.time()
        try:
            samples, sr = kokoro.create(norm, voice=voice, speed=speed, lang=lang)
            dur = len(samples) / sr
            fname = f"{sid}.mp3"
            tmp = audio_dir / (fname + ".part")
            sf.write(str(tmp), samples, sr, format="MP3",
                     bitrate_mode="VARIABLE", compression_level=0.6)
            os.replace(tmp, audio_dir / fname)
            idx["clips"][sid] = {"f": fname, "d": round(dur, 2), "h": h,
                                 "voice": voice, "speed": speed,
                                 "at": time.strftime("%Y-%m-%dT%H:%M:%S")}
            ok += 1
            print(f"  [{n}/{len(todo)}] {sid}  {dur:5.1f}s audio in {time.time() - t0:5.1f}s",
                  flush=True)
        except Exception as exc:
            idx["clips"][sid] = {"error": f"{type(exc).__name__}: {exc}", "h": h}
            fail += 1
            print(f"  [{n}/{len(todo)}] {sid}  FAILED: {exc}", flush=True)
        save_index(audio_dir, idx)      # after every clip: Ctrl-C loses at most one

    total = sum(v.get("d", 0) for v in idx["clips"].values() if not v.get("error"))
    print(f"[{name}] {ok} ok, {fail} failed, {cached} cached - {total / 60:.1f} min of narration")
    if fail:
        print(f"[{name}] re-run the same command to retry just the failures")
    return fail == 0


def main(argv: list[str]) -> int:
    _rebind(project_dir(argv))
    voice, speed, only, check = DEFAULT_VOICE, DEFAULT_SPEED, None, False
    args, i = [], 0
    while i < len(argv):
        a = argv[i]
        if a == "--voice":
            voice = argv[i + 1]; i += 2
        elif a == "--speed":
            speed = float(argv[i + 1]); i += 2
        elif a == "--only":
            only = {x.strip() for x in argv[i + 1].split(",") if x.strip()}; i += 2
        elif a == "--dir":
            i += 2
        elif a == "--check":
            check = True; i += 1
        elif a == "--fetch-models":
            return 0 if fetch_models() else 1
        else:
            args.append(a); i += 1

    targets = args or all_decks()
    if not targets:
        print(f"no decks found in {DECKS_DIR}")
        return 1
    return 0 if all(narrate(t, voice, speed, only, check) for t in targets) else 1


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
