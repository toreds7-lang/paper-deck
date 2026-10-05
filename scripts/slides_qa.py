"""Headless render QA for built slide decks.

    python slides_qa.py                          # every deck in ./slides
    python slides_qa.py mini_omni
    python slides_qa.py mini_omni --shots 3,7,12 # also save PNGs of those slides

Loads each deck from file:// in Chromium and checks what a human reviewer
cannot check reliably by eye: console errors, every mermaid diagram actually
becoming an SVG, content overflowing the 720px slide box, figures loading,
keyboard navigation reaching every slide, grid/notes/theme modes, the diagram
lightbox, deep links, one print page per slide, and that every narration clip in
the manifest exists on disk with a plausible duration.

Screenshots land in slides_assets/_qa/. Read a few of them — the checks catch
breakage, but only looking catches a slide that is merely ugly.

Needs:  pip install playwright  &&  python -m playwright install chromium
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

# Console noise that is expected and harmless on file://
IGNORE = ("net::ERR_FILE_NOT_FOUND", "favicon", "Download the React DevTools")


def project_dir(argv: list[str]) -> Path:
    if "--dir" in argv:
        return Path(argv[argv.index("--dir") + 1]).resolve()
    return Path(os.environ.get("PAPER_DECK_DIR") or Path.cwd()).resolve()


PROJECT = Path.cwd()
SHOT_DIR = PROJECT / "slides_assets" / "_qa"


def _rebind(root: Path) -> None:
    global PROJECT, SHOT_DIR
    PROJECT, SHOT_DIR = root, root / "slides_assets" / "_qa"


def all_decks() -> list[str]:
    d = PROJECT / "slides"
    if not d.exists():
        return []
    return sorted(p.stem for p in d.glob("*.json") if not p.name.endswith(".scripts.json"))


def qa(page, name: str, shots: set[int]) -> list[str]:
    fails: list[str] = []
    errors: list[str] = []
    page.on("console", lambda m: errors.append(f"{m.type}: {m.text}")
            if m.type == "error" and not any(x in m.text for x in IGNORE) else None)
    page.on("pageerror", lambda e: errors.append(f"pageerror: {e}"))

    html = PROJECT / f"{name}_slides.html"
    if not html.exists():
        return [f"{name}: {html.name} not built"]
    page.goto(html.as_uri())
    page.wait_for_function("window.__deckReady === true", timeout=30000)

    n = page.evaluate("SLIDES.length")
    print(f"  {n} slides")

    # walk every slide with the keyboard, exactly as a presenter would
    for i in range(n):
        page.keyboard.press("Home") if i == 0 else page.keyboard.press("ArrowRight")
        page.wait_for_timeout(190)

        cur = page.evaluate("document.querySelector('.slide.current')?.dataset.i")
        if cur is None or int(cur) != i:
            fails.append(f"{name}: keyboard nav landed on {cur}, expected {i}")
            continue

        info = page.evaluate("""() => {
          const el = document.querySelector('.slide.current');
          const vizzes = [...el.querySelectorAll('.viz')];
          const body = el.querySelector('.s-body') || el;
          return {
            id: el.id,
            svgCount: vizzes.filter(v => v.querySelector('svg')).length,
            imgOk: vizzes.filter(v => { const i = v.querySelector('img');
                                        return i ? i.naturalWidth > 0 : false; }).length,
            imgCount: vizzes.filter(v => v.querySelector('img')).length,
            overflowY: Math.max(0, el.scrollHeight - el.clientHeight),
            bodyOverflow: Math.max(0, body.scrollHeight - body.clientHeight)
          };
        }""")

        if page.evaluate(f"!!(SLIDES[{i}].mermaid)") and info["svgCount"] < 1:
            fails.append(f"{name} {info['id']}: mermaid did not render to SVG")
        if info["imgCount"] and info["imgOk"] < info["imgCount"]:
            fails.append(f"{name} {info['id']}: figure image failed to load")
        if info["overflowY"] > 2 or info["bodyOverflow"] > 2:
            fails.append(f"{name} {info['id']}: content overflows by "
                         f"{max(info['overflowY'], info['bodyOverflow'])}px")

        if (i + 1) in shots:
            SHOT_DIR.mkdir(parents=True, exist_ok=True)
            page.screenshot(path=str(SHOT_DIR / f"{name}_s{i + 1:02d}.png"))

    # diagram lightbox: the reading surface for anything projected
    viz_slide = page.evaluate("SLIDES.findIndex(s => s.mermaid || s.figure)")
    if viz_slide >= 0:
        page.goto(html.as_uri() + f"#/{viz_slide + 1}")
        page.wait_for_function("window.__deckReady === true", timeout=20000)
        page.wait_for_timeout(900)
        page.click(".slide.current .viz")
        page.wait_for_timeout(400)
        if not page.evaluate("document.querySelector('#lb').classList.contains('on')"):
            fails.append(f"{name}: lightbox did not open")
        elif not page.evaluate("!!document.querySelector('#lbinner svg, #lbinner img')"):
            fails.append(f"{name}: lightbox opened empty")
        page.keyboard.press("Escape")
        page.wait_for_timeout(250)
        if page.evaluate("document.querySelector('#lb').classList.contains('on')"):
            fails.append(f"{name}: Escape did not close the lightbox")

    # print path: exactly one page per slide
    SHOT_DIR.mkdir(parents=True, exist_ok=True)
    pdf_path = SHOT_DIR / f"{name}_print.pdf"
    page.pdf(path=str(pdf_path), width="1280px", height="720px",
             print_background=True, prefer_css_page_size=True)
    try:
        import fitz
        pages = len(fitz.open(pdf_path))
        if pages != n:
            fails.append(f"{name}: print produced {pages} pages for {n} slides")
    except ImportError:
        pass

    # narration manifest must point at files that exist, with sane durations
    clips = page.evaluate("AUDIO")
    for sid, c in (clips or {}).items():
        f = PROJECT / c["src"]
        if not f.exists():
            fails.append(f"{name} {sid}: narration file missing on disk ({c['src']})")
        elif not (3 < c.get("dur", 0) < 180):
            fails.append(f"{name} {sid}: narration duration {c.get('dur')}s is implausible")
    if clips:
        print(f"  {len(clips)}/{n} slides narrated "
              f"({sum(c.get('dur', 0) for c in clips.values()) / 60:.1f} min)")

    # modes
    page.keyboard.press("g"); page.wait_for_timeout(300)
    if page.evaluate("document.body.dataset.mode") != "grid":
        fails.append(f"{name}: grid mode did not open")
    if page.evaluate("document.querySelectorAll('#grid .thumb').length") != n:
        fails.append(f"{name}: grid thumbnail count mismatch")
    if shots:
        page.screenshot(path=str(SHOT_DIR / f"{name}_grid.png"))
    page.keyboard.press("g"); page.wait_for_timeout(200)

    page.keyboard.press("s"); page.wait_for_timeout(200)
    if page.evaluate("document.body.dataset.notes") != "1":
        fails.append(f"{name}: notes pane did not open")
    page.keyboard.press("s"); page.wait_for_timeout(150)

    page.keyboard.press("Home"); page.wait_for_timeout(200)
    before = page.evaluate("document.documentElement.getAttribute('data-theme')")
    page.keyboard.press("t"); page.wait_for_timeout(700)
    after = page.evaluate("document.documentElement.getAttribute('data-theme')")
    if after == before or after not in ("light", "dark"):
        fails.append(f"{name}: theme toggle failed ({before} -> {after})")
    if page.evaluate("!!SLIDES[0].mermaid") and not page.evaluate(
            "!!document.querySelector('.slide.current .viz svg')"):
        fails.append(f"{name}: mermaid lost after theme toggle")

    page.goto(html.as_uri() + "#/12")
    page.wait_for_function("window.__deckReady === true", timeout=20000)
    page.wait_for_timeout(400)
    if n >= 12 and page.evaluate("document.querySelector('.slide.current')?.dataset.i") != "11":
        fails.append(f"{name}: deep link #/12 did not restore slide 12")

    for e in errors[:6]:
        fails.append(f"{name}: console {e}")
    return fails


def main(argv: list[str]) -> int:
    _rebind(project_dir(argv))
    from playwright.sync_api import sync_playwright

    shots: set[int] = set()
    args, i = [], 0
    while i < len(argv):
        if argv[i] == "--shots":
            shots = {int(x) for x in argv[i + 1].split(",")}; i += 2
        elif argv[i] == "--dir":
            i += 2
        else:
            args.append(argv[i]); i += 1
    targets = args or all_decks()
    if not targets:
        print(f"no decks found in {PROJECT / 'slides'}")
        return 1

    all_fails = []
    with sync_playwright() as pw:
        browser = pw.chromium.launch()
        ctx = browser.new_context(viewport={"width": 1600, "height": 900})
        for name in targets:
            print(f"[{name}]")
            page = ctx.new_page()
            try:
                all_fails += qa(page, name, shots)
            except Exception as exc:
                all_fails.append(f"{name}: QA crashed: {type(exc).__name__}: {exc}")
            page.close()
        browser.close()

    print()
    if all_fails:
        print(f"{len(all_fails)} problem(s):")
        for f in all_fails:
            print(f"  FAIL {f}")
        return 1
    print("all checks passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
