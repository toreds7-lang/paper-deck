"""Build a self-contained, presentation-style HTML deck from a deck JSON file.

    python slides_build.py                      # build every deck in ./slides
    python slides_build.py mini_omni            # -> mini_omni_slides.html
    python slides_build.py --check              # validate only, exit 1 on error
    python slides_build.py --draft              # allow missing narration scripts
    python slides_build.py --merge-scripts      # fold slides/<d>.scripts.json in
    python slides_build.py --figscan paper.pdf 5   # list figure rects on page 5

Content lives in <project>/slides/<deck>.json so it can be reviewed and
fact-checked as data; this script only renders it. Figures named by a slide are
cropped straight out of the source PDF with PyMuPDF and base64-inlined, so the
built deck's visuals need no sibling image folder and work from file://.

Paths: the deck template and the vendored mermaid come from the skill's own
assets/ directory; everything else is relative to the project directory (the
current working directory, or --dir).
"""
from __future__ import annotations

import base64
import json
import os
import re
import shutil
import sys
from pathlib import Path
from typing import Any

# Consoles outside UTF-8 (e.g. cp949) crash on a paper's "∗" or "→".
try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

SKILL_DIR = Path(__file__).resolve().parent.parent
SKILL_ASSETS = SKILL_DIR / "assets"
TEMPLATE = SKILL_ASSETS / "slides_template.html"

LAYOUTS = {"", "split"}
TYPES = {
    "cover", "divider", "analogy", "toc", "summary", "keywords", "problem",
    "contrib", "mindmap", "figure", "mechanism", "training", "data", "results",
    "case", "limits", "improve", "takeaway", "refs",
}

# narration budget: ~155 wpm -> roughly 45-75 s of speech
WORDS_MIN, WORDS_MAX = 105, 205


def project_dir(argv: list[str]) -> Path:
    if "--dir" in argv:
        return Path(argv[argv.index("--dir") + 1]).resolve()
    return Path(os.environ.get("PAPER_DECK_DIR") or Path.cwd()).resolve()


PROJECT = Path.cwd()          # rebound in main()
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


# ─── injection ──────────────────────────────────────────────────────────────

def _inject(html: str, marker: str, value: Any) -> str:
    """Replace `/*MARKER*/ <anything>;` with `/*MARKER*/ <json>;`.

    Always call this against the pristine template. The pattern is non-greedy to
    the first ';', so re-injecting into an already-built file would truncate the
    payload at the first semicolon inside it.
    """
    payload = json.dumps(value, ensure_ascii=False)
    # "</" would close the enclosing <script> element;   and   are raw
    # line terminators in JS source. Both are valid JS string escapes.
    payload = (payload.replace("</", "<\\/")
                      .replace(" ", "\\u2028")
                      .replace(" ", "\\u2029"))
    pat = re.compile(r"/\*" + re.escape(marker) + r"\*/[\s\S]*?;")
    new, n = pat.subn(lambda _m: f"/*{marker}*/ {payload};", html, count=1)
    if n == 0:
        raise RuntimeError(f"template marker {marker} not found")
    return new


# ─── figures ────────────────────────────────────────────────────────────────

def _render_figure(spec: dict, cache: dict) -> str | None:
    """Crop a region out of a PDF page and return it as a data: URI."""
    import fitz

    pdf, page_no = spec.get("pdf"), spec.get("page")
    if not pdf or not page_no:
        return None
    zoom = spec.get("zoom", 2.0)
    key = f"{pdf}|{page_no}|{spec.get('rect')}|{zoom}"
    if key in cache:
        return cache[key]

    path = PROJECT / pdf
    if not path.exists():
        print(f"  ! figure source missing: {pdf}")
        return None
    doc = fitz.open(path)
    try:
        page = doc[page_no - 1]
        rect = spec.get("rect")
        pix = page.get_pixmap(matrix=fitz.Matrix(zoom, zoom),
                              clip=fitz.Rect(*rect) if rect else None, alpha=False)
        png = pix.tobytes("png")
    finally:
        doc.close()
    uri = "data:image/png;base64," + base64.b64encode(png).decode("ascii")
    cache[key] = uri
    return uri


def figscan(pdf_name: str, page_no: int | None = None) -> None:
    """Print image-block rects and figure captions, to pick crops by hand.

    Vector figures have no image block, so use the caption's y0 as the bottom of
    the crop and the previous text block's bottom as the top.
    """
    import fitz

    doc = fitz.open(PROJECT / pdf_name)
    pages = [page_no - 1] if page_no else range(len(doc))
    for i in pages:
        page = doc[i]
        d = page.get_text("dict")
        imgs = [b for b in d["blocks"] if b.get("type") == 1]
        caps = []
        for b in d["blocks"]:
            if b.get("type") != 0:
                continue
            txt = " ".join(s["text"] for ln in b.get("lines", []) for s in ln.get("spans", []))
            if re.match(r"\s*(Figure|Table)\s*\d+", txt):
                caps.append(([round(v, 1) for v in b["bbox"]], txt[:110]))
        if not imgs and not caps:
            continue
        print(f"\n-- page {i + 1} (size {page.rect.width:.0f}x{page.rect.height:.0f})")
        for b in imgs:
            print(f"   image rect {[round(v, 1) for v in b['bbox']]}")
        for bbox, txt in caps:
            print(f"   caption  {bbox}  {txt}")
    doc.close()


# ─── validation ─────────────────────────────────────────────────────────────

def validate(deck: dict, name: str, draft: bool = False) -> list[str]:
    """draft=True downgrades 'missing narration' to a warning, so slide content
    can be laid out and reviewed before the scripts are written."""
    errs: list[str] = []
    warns: list[str] = []
    slides = deck.get("slides") or []
    if not slides:
        return [f"{name}: no slides"]

    seen, types_present = set(), set()
    for i, s in enumerate(slides):
        tag = f"{name}[{i + 1}]"
        sid = s.get("id")
        if not sid or not re.match(r"^s\d{2}$", str(sid)):
            errs.append(f"{tag}: bad or missing id {sid!r} (want s01..s99)")
        elif sid in seen:
            errs.append(f"{tag}: duplicate id {sid}")
        seen.add(sid)

        t = s.get("type", "")
        types_present.add(t)
        if t and t not in TYPES:
            errs.append(f"{tag}: unknown type {t!r}")
        if s.get("layout", "") not in LAYOUTS:
            errs.append(f"{tag}: unknown layout {s.get('layout')!r}")
        if t not in ("cover", "divider", "analogy") and not s.get("title"):
            errs.append(f"{tag}: missing title")
        if t == "analogy" and not s.get("metaphor"):
            errs.append(f"{tag}: analogy slide without a metaphor")

        script = (s.get("script") or "").strip()
        if not script:
            (warns if draft else errs).append(f"{tag} {sid}: missing narration script")
        else:
            n = len(script.split())
            if n < WORDS_MIN or n > WORDS_MAX:
                warns.append(f"{tag} {sid}: script is {n} words (want {WORDS_MIN}-{WORDS_MAX})")
            if re.search(r"[*_`#]|\\\w+\{|\$\$?[^$]+\$", script):
                errs.append(f"{tag} {sid}: script contains markup/LaTeX - TTS reads it aloud")

        # content budgets: what actually keeps a slide inside 720px
        if len(s.get("bullets") or []) > 7:
            warns.append(f"{tag} {sid}: {len(s['bullets'])} bullets (max 7)")
        for b in (s.get("bullets") or []):
            txt = b if isinstance(b, str) else (b.get("h", "") + b.get("t", ""))
            if len(txt) > 165:
                warns.append(f"{tag} {sid}: bullet is {len(txt)} chars (max 165)")
        if len(s.get("cards") or []) > 3:
            errs.append(f"{tag} {sid}: {len(s['cards'])} cards (max 3)")
        if len(s.get("arrows") or []) > 5:
            warns.append(f"{tag} {sid}: {len(s['arrows'])} arrow rows (max 5)")
        tbl = s.get("table")
        if tbl and len(tbl.get("rows") or []) > 9:
            warns.append(f"{tag} {sid}: table has {len(tbl['rows'])} rows (max 9)")
        for g in (s.get("chips") or []):
            if len(g.get("items") or []) > 10:
                warns.append(f"{tag} {sid}: chip group '{g.get('label')}' has {len(g['items'])} (max 10)")

        mm = s.get("mermaid")
        if mm:
            if not re.search(r"(-->|---|->|==>|\bgraph\b|\bflowchart\b|\bmindmap\b|\bsequenceDiagram\b)", mm):
                errs.append(f"{tag} {sid}: mermaid has no edges/diagram keyword")
            if mm.lstrip().startswith("mindmap"):
                if "-->" in mm:
                    errs.append(f"{tag} {sid}: mindmap must not contain '-->' edges")
                nodes = len([l for l in mm.splitlines() if l.strip()]) - 1
                if nodes > 26:
                    warns.append(f"{tag} {sid}: mindmap has ~{nodes} nodes (max 26 at 1280x720)")
            if s.get("figure"):
                errs.append(f"{tag} {sid}: has both mermaid and figure; pick one")

    need = {
        "cover": "a title slide", "toc": "an explained table of contents",
        "summary": "a one-page summary", "keywords": "a keywords slide",
        "mindmap": "a mind-map", "contrib": "a contributions-vs-prior-limits slide",
        "limits": "a limitations slide", "improve": "an improvements slide",
        "analogy": "at least one analogy slide",
    }
    for t, label in need.items():
        if t not in types_present:
            errs.append(f"{name}: missing {label} (type={t!r})")
    if not any(s.get("mermaid", "").lstrip().startswith(("flowchart", "graph", "sequenceDiagram"))
               for s in slides):
        errs.append(f"{name}: no mermaid flowchart for a core algorithm")

    for w in warns:
        print(f"  ~ {w}")
    return errs


# ─── build ──────────────────────────────────────────────────────────────────

def load_deck(name: str) -> dict:
    p = DECKS_DIR / f"{name}.json"
    if not p.exists():
        raise SystemExit(f"deck json not found: {p}")
    return json.loads(p.read_text(encoding="utf-8"))


def load_audio_manifest(name: str) -> dict:
    p = OUT_ASSETS / name / "audio" / "manifest.json"
    if not p.exists():
        return {}
    try:
        data = json.loads(p.read_text(encoding="utf-8"))
    except Exception:
        return {}
    out = {}
    for sid, rec in (data.get("clips") or {}).items():
        if rec.get("error") or not rec.get("f"):
            continue
        out[sid] = {"src": f"slides_assets/{name}/audio/{rec['f']}", "dur": rec.get("d", 0)}
    return out


def ensure_mermaid() -> None:
    """Put the vendored mermaid beside the deck so it works offline."""
    dst = OUT_ASSETS / "mermaid.min.js"
    src = SKILL_ASSETS / "mermaid.min.js"
    if dst.exists() or not src.exists():
        return
    dst.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(src, dst)
    print(f"  vendored mermaid -> {dst.relative_to(PROJECT)}")


def merge_scripts(name: str) -> bool:
    """Fold slides/<deck>.scripts.json into slides/<deck>.json.

    Narration is authored separately so that writing scripts can never corrupt
    slide content; this is the only step that joins them.
    """
    deck_p, scr_p = DECKS_DIR / f"{name}.json", DECKS_DIR / f"{name}.scripts.json"
    if not scr_p.exists():
        print(f"[{name}] no {scr_p.name} to merge")
        return False
    deck = json.loads(deck_p.read_text(encoding="utf-8"))
    scripts = json.loads(scr_p.read_text(encoding="utf-8"))

    n, missing = 0, []
    for s in deck["slides"]:
        text = (scripts.get(s["id"]) or "").strip()
        if text:
            s["script"] = text
            n += 1
        elif not (s.get("script") or "").strip():
            missing.append(s["id"])
    extra = sorted(set(scripts) - {s["id"] for s in deck["slides"]})

    tmp = deck_p.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(deck, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    os.replace(tmp, deck_p)
    print(f"[{name}] merged {n}/{len(deck['slides'])} scripts"
          + (f", missing: {', '.join(missing)}" if missing else "")
          + (f", unknown ids ignored: {', '.join(extra)}" if extra else ""))
    return not missing


def build(name: str, check_only: bool = False, draft: bool = False) -> bool:
    deck = load_deck(name)
    print(f"[{name}] {len(deck.get('slides', []))} slides")
    errs = validate(deck, name, draft=draft)
    if errs:
        for e in errs:
            print(f"  ERROR {e}")
        return False
    if check_only:
        print(f"[{name}] ok")
        return True

    slides = deck["slides"]
    figcache: dict[str, str] = {}
    n_fig = 0
    for s in slides:
        fig = s.get("figure")
        if fig and fig.get("pdf"):
            uri = _render_figure(fig, figcache)
            if uri:
                s["figure"] = {"src": uri, "cap": fig.get("cap", "")}
                n_fig += 1
            else:
                s.pop("figure", None)

    ensure_mermaid()
    audio = load_audio_manifest(name)
    html = TEMPLATE.read_text(encoding="utf-8")        # always pristine
    html = _inject(html, "__META__", deck.get("meta", {}))
    html = _inject(html, "__SLIDES__", slides)
    html = _inject(html, "__AUDIO__", audio)
    html = html.replace(
        "<body ",
        f"<!-- GENERATED by paper-deck from slides/{name}.json - DO NOT EDIT -->\n<body ", 1)

    out = PROJECT / f"{name}_slides.html"
    tmp = out.with_suffix(".html.tmp")
    tmp.write_text(html, encoding="utf-8")
    os.replace(tmp, out)
    print(f"[{name}] -> {out.name}  ({out.stat().st_size / 1024:.0f} KB, "
          f"{n_fig} figures inlined, {len(audio)}/{len(slides)} clips)")
    return True


def main(argv: list[str]) -> int:
    _rebind(project_dir(argv))
    flags = {a for a in argv if a.startswith("--")}
    args = [a for a in argv if not a.startswith("--")]
    if "--dir" in argv:                     # drop --dir's value from positionals
        val = argv[argv.index("--dir") + 1]
        args = [a for a in args if a != val]

    if "--figscan" in flags:
        pdf = args[0]
        page = int(args[1]) if len(args) > 1 and args[1].isdigit() else None
        figscan(pdf, page)
        return 0

    targets = args or all_decks()
    if not targets:
        print(f"no decks found in {DECKS_DIR}")
        return 1

    if "--merge-scripts" in flags:
        return 0 if all(merge_scripts(t) for t in targets) else 1

    ok = True
    for t in targets:
        try:
            ok &= build(t, check_only="--check" in flags, draft="--draft" in flags)
        except SystemExit as e:
            print(f"  ERROR {e}")
            ok = False
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
