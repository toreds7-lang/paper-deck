---
name: paper-deck
description: Turn a research paper or technical report PDF into a standalone, narrated, presentation-style HTML slide deck — one-page summary, explained table of contents, mermaid mind-map and algorithm flowcharts, contributions framed against the limitations they overcome, keywords, plain-language analogies for the hard ideas, an honest critique slide, and a speaker script per slide that can be rendered to speech with Kokoro TTS. Use this skill whenever someone wants a paper, preprint, arXiv PDF, whitepaper, RFC, spec or internal technical report explained, taught, summarized visually, or turned into slides, a deck, a presentation, a talk, a lecture, a seminar, a reading-group walkthrough or a journal-club session. Trigger it for "explain this paper", "make slides from this PDF", "summarize this report as a presentation", "I need to present this to my team", "help me understand this paper", "build a lecture on this", or when someone drops a technical PDF and asks what is in it — even if they never say the word "slides". Also use it when asked to add narration or speaker notes to an existing deck built this way.
---

# paper-deck

Builds a 16:9 HTML deck that teaches one paper. The deck is a single file you
open by double-click: figures are cropped from the PDF and inlined, diagrams are
mermaid, and every slide carries a speaker script that can become audio.

The deck is generated from a JSON file of slide content, not written as HTML by
hand. That split is the whole point — content can be fact-checked, re-reviewed
and re-narrated as data, and a template fix lands in every deck at once.

## Produce this

```
<project>/
  paper.pdf                     the source
  slides/<deck>.json            slide content  <- you author this
  slides/<deck>.scripts.json    narration      <- a subagent authors this
  <deck>_slides.html            the deliverable
  slides_assets/
    mermaid.min.js              copied in automatically (offline support)
    <deck>/audio/s01.mp3 …      only if narrating
```

`<deck>` is a slug of the PDF name: `mini-omni.pdf` → `mini_omni`.

## Setup

```bash
pip install pymupdf                 # figure cropping — always needed
pip install playwright && python -m playwright install chromium   # render QA
pip install kokoro-onnx soundfile   # narration audio, only if asked
```

Kokoro needs no torch, no GPU and no separate espeak-ng install — the
`espeakng-loader` wheel bundles the binary. It runs at roughly 2× realtime on
CPU. Models are ~353 MB, fetched once with `slides_tts.py --fetch-models`.

Run scripts with `--dir <project>` or from the project directory.

## Workflow

Narration audio is slow and needs a large download, so **write the scripts
always and render audio only when asked.** A written script costs nothing and
makes the deck useful immediately; audio costs half an hour of CPU per deck.

### 1. Read the paper properly

Extract the full text and read it — do not skim the abstract and guess:

```bash
python -c "import fitz;d=fitz.open('paper.pdf');print(chr(10).join(p.get_text() for p in d))" > /tmp/paper.txt
```

You need: the thesis in one sentence, the section structure, the core mechanism
in enough detail to draw its data flow, the training/method recipe, the
datasets, every results table, what the authors say about prior work's
limitations, what they admit about their own, and the figure inventory.

For a long or dense paper, a subagent reading it in parallel with your own pass
is worth it. Ask it for mechanism detail and exact numbers, not vibes.

### 2. Find the figures

```bash
python <skill>/scripts/slides_build.py --figscan paper.pdf
```

This prints image-block rects and figure captions per page. Pick the two to five
figures that carry real explanatory weight — architecture, the core mechanism,
the training stages.

Vector figures have no image block, so crop from just under the previous text
block down to the caption's `y0`. **Render your crop and look at it before
committing.** Crops that amputate their own subject are the single most common
defect in these decks — a training-stages figure cropped below its first two
stage headings still looks fine in a thumbnail, and is wrong on a slide that
promises five stages.

### 3. Author the slide content

Write `slides/<deck>.json`. Read `references/deck-schema.md` for the full slide
schema, the block types and a worked example.

Use this spine — about 24 slides. It exists because a reader needs orientation
before mechanism, and mechanism before judgement:

| # | type | what it does |
|---|---|---|
| 1 | `cover` | title, authors, arXiv/date, one-line thesis |
| 2 | `toc` | every section plus a one-line *what you'll learn here* |
| 3 | `summary` | Problem / Idea / Result on one page |
| 4 | `keywords` | chips grouped by architecture, mechanism, data, framing |
| 5 | `problem` | what was broken before this paper |
| 6 | `contrib` | prior limitation → the contribution that removes it |
| 7 | `mindmap` | mermaid mindmap of the whole paper |
| 8 | `figure` | architecture, from the PDF |
| 9–16 | `mechanism` ×3–4 | each = flowchart + walkthrough, **each followed by** an `analogy` |
| 17 | `training` | the recipe / stages |
| 18 | `data` | datasets, and any new asset the paper ships |
| 19 | `results` | the tables, with the key delta highlighted |
| 20 | `case` | a qualitative example |
| 21 | `limits` | two cards: what authors state / what you observed |
| 22 | `improve` | concrete suggested improvements |
| 23 | `takeaway` | three things to remember |
| 24 | `refs` | links and background reading |

Then `python <skill>/scripts/slides_build.py --draft` to lay it out before any
narration exists, and `slides_qa.py` to catch overflow early.

### 4. Write the narration

Delegate this to a subagent. It writes `slides/<deck>.scripts.json` —
`{"s01": "...", "s02": "..."}` — a separate file so that writing scripts can
never corrupt slide content, and so the two can be reviewed independently.

Give the subagent the constraints in **Narration rules** below verbatim. Then:

```bash
python <skill>/scripts/slides_build.py --merge-scripts
python <skill>/scripts/slides_build.py
```

### 5. Review, three passes

This is where deck quality actually comes from. Do not skip to shipping.

**Pass 1 — accuracy.** A subagent re-opens the PDF and checks every number,
model size, dataset count, equation, quote and figure caption against the
source, and verifies that each criticism the deck makes is actually supported.
Have it *report* rather than edit, so it cannot collide with other work. Then
verify its findings yourself before acting — especially figure claims, which you
can check by rendering the crop and looking. A false accusation against a paper
is worse than a missing one.

**Pass 2 — pedagogy and narration.** Does each analogy match the mechanism it
explains? Do the flowcharts show the real data path, or a plausible-looking
invention? Does each script narrate the slide that is actually on screen?

**Pass 3 — render QA.** `python <skill>/scripts/slides_qa.py --shots 1,3,7`
then *read several screenshots*. The checks catch breakage; only looking catches
a slide that is merely ugly.

### 6. Narrate, if asked

```bash
python <skill>/scripts/slides_tts.py --fetch-models   # once, ~353 MB
python <skill>/scripts/slides_tts.py                  # ~30 min per deck on CPU
python <skill>/scripts/slides_build.py                # inject clips + durations
```

Resumable: a clip re-renders only when missing, changed, or previously failed,
so re-running retries exactly the failures. Run it in the background and keep
working. When a clip mispronounces something, add it to the deck's
`meta.pronounce` map and re-run — only that slide re-renders.

## Narration rules

Give these to the narration subagent as-is. They exist because the text is fed
verbatim to a speech engine, and because a script that drifts from its slide is
worse than no script.

- **105–205 words per slide**, target 130–170. That is 45–75 seconds.
- **Plain prose only.** No markdown, no asterisks, backticks, hashes or
  underscores, no LaTeX, no arrows or bullet glyphs — a TTS engine reads them
  aloud. Write numbers as they should be said: "seventy-seven point two five".
- **Narrate the slide that is there.** Read its title, bullets, table, diagram
  and analogy, and speak to those. Never describe a slide that does not exist.
- **Open by orienting, close by handing off** to what genuinely comes next.
- On **diagram slides**, walk the flow in the order the arrows go. Listing the
  boxes teaches nothing.
- On **table slides**, give the one comparison that matters rather than reading
  every cell, and say what it means.
- On **analogy slides**, tell the picture first, then connect each mapped pair.
  These are where the listener either gets it or does not.
- On **limitations slides**, keep the split audible: "the authors acknowledge"
  versus "criticism worth forming on your own reading".
- Vary sentence length; never start a script with "This slide".

## Writing content that earns the slide

**Analogies carry the deck.** One per core mechanism, each on its own slide
after the mechanism it explains. A good one maps three or four specific pairs
and then says where it breaks — an analogy without its failure mode is
misinformation. Reach for everyday machinery: a sung round for staggered
parallel streams, progressive JPEG for coarse-to-fine layers, a simultaneous
interpreter for overlapped thinking and speaking.

**Diagrams must show the real mechanism.** Draw the actual data path from the
paper, with the paper's component names. A diagram that merely looks technical
is worse than none. Keep mermaid flowcharts to about 10 nodes and prefer
`flowchart TB` in split layouts — a wide `LR` diagram letterboxes into a thin
strip in a portrait panel. Keep mindmaps under ~26 nodes.

**Be honest and be specific in the critique.** The `limits` slide separates what
the authors state — with section references — from what you observed. Real
findings are things like: a paper whose thesis is latency reporting no latency
numbers; a dataset quoted at two different sizes in the table and the prose; a
headline comparison its own table does not support. Check each one before you
write it down.

**The `contrib` slide is the spine of the argument.** Each row pairs a concrete
prior limitation with the mechanism that removes it. If you cannot name the
limitation, you have not understood the contribution.

When decks for several related papers are requested, ask whether they should be
independent or tell one connected story — it changes the structure of all of
them.

## Commands

```bash
slides_build.py                     # build every deck in ./slides
slides_build.py <deck> --draft      # lay out before scripts exist
slides_build.py --check             # validate only, exit 1 on error
slides_build.py --merge-scripts     # fold in <deck>.scripts.json
slides_build.py --figscan p.pdf 5   # figure rects + captions on page 5
slides_tts.py --fetch-models        # one-time model download
slides_tts.py [<deck>] [--only s07,s12] [--voice af_bella] [--check]
slides_qa.py [<deck>] [--shots 1,3,7]
```

All accept `--dir <project>`.

The validator enforces what keeps a deck readable: required coverage (summary,
explained TOC, mind-map, keywords, contributions, limitations, improvements, at
least one analogy and one algorithm flowchart), narration word counts, no markup
inside a script, mindmaps without flowchart edges, and per-slide content budgets
that keep text inside the 720 px box. Treat its warnings as real.

## Using the finished deck

Arrow keys or space to move, `G` overview grid, `S` speaker script, `P` play
narration, `A` auto-advance, `T` theme, `F` fullscreen, `?` shortcuts. Click any
diagram to zoom. `Ctrl-P` prints one slide per page. `#/12` in the URL deep-links
to slide 12.

Browsers block audio until the page is interacted with, so the first `P` press
is what unlocks narration. The deck stays fully usable with no audio present.

To share it, send the HTML alone for a silent deck, or the HTML plus
`slides_assets/` for narration.
