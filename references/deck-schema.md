# Deck JSON schema

Contents: [File shape](#file-shape) · [Slide fields](#slide-fields) ·
[Layout](#layout) · [Blocks](#blocks) · [Special slide types](#special-slide-types) ·
[Inline formatting](#inline-formatting) · [Diagrams](#diagrams) ·
[Figures](#figures) · [Worked example](#worked-example) · [Budgets](#budgets)

## File shape

```json
{
  "meta": {
    "title": "Mini-Omni — Hear, Talk While Thinking",
    "deck": "mini_omni",
    "paper": "arXiv:2408.16725v3",
    "pronounce": { "SNAC": "snack", "0.5B": "zero point five billion" }
  },
  "slides": [ { "id": "s01", "…": "…" } ]
}
```

`meta.title` becomes the browser tab title. `meta.pronounce` is applied only to
narration before it reaches the speech engine — it never changes slide text.
Put a term here the moment a clip says it wrong; re-running the narration
re-renders just the affected slides.

## Slide fields

Every slide takes these. All are optional except `id`.

| field | meaning |
|---|---|
| `id` | `s01`…`s99`, unique, in order. Also the audio filename and deep-link target. |
| `type` | drives styling and the coverage validator — see the spine in SKILL.md |
| `kicker` | small uppercase eyebrow, e.g. `"5 · Core algorithm"` |
| `badge` | small pill next to the kicker |
| `title` | the slide headline |
| `lead` | one or two sentences under the title, larger and dimmer |
| `foot` | small footnote line at the bottom |
| `script` | the narration. Plain prose, 105–205 words. See SKILL.md. |

Keep `kicker` numbering consistent with the `toc` slide's numbering — a deck
whose kickers drift past its own roadmap reads as sloppy.

## Layout

Default: title, then blocks stacked and vertically centred.

`"layout": "split"` puts blocks on the left and the diagram or figure on the
right:

```json
{ "layout": "split", "sideWide": "l", "bullets": [...], "mermaid": "flowchart TB\n…" }
```

- `sideWide`: `"l"` gives the text column more width, `"r"` the visual.
- `vizFirst: true` puts the visual on the left.

A split panel is portrait, so `flowchart TB` fills it and `flowchart LR`
letterboxes into a thin strip.

## Blocks

Render in this order when several are present: chips, arrows, toc, stats, cards,
bullets, table, callout, then the visual.

### bullets

```json
"bullets": [
  { "h": "Text goes first", "t": "Padding guarantees the text token precedes the audio." },
  "a plain string also works"
]
```

### cards — 2 or 3 side by side

```json
"cards": [
  { "title": "Problem", "tone": "bad",  "text": "…" },
  { "title": "Idea",                    "text": "…" },
  { "title": "Result",  "tone": "good", "items": ["…", "…"], "big": "4.5", "sub": "WER" }
]
```

`tone`: `good` | `bad` | `warn`. Use `items` for a list, `text` for prose,
`big`+`sub` for a headline number.

### table

```json
"table": {
  "sm": true,
  "head": ["Model", "test-clean", "test-other"],
  "rows": [
    ["whisper-small", "3.4", "7.6"],
    { "cells": ["**Mini-Omni**", "**4.5**", "**9.7**"], "hl": true }
  ],
  "note": "What the numbers mean, and any caveat."
}
```

`hl` highlights the row that matters. `sm` shrinks type for denser tables.

### arrows — limitation → contribution

The `contrib` slide's core block. Red-edged left, green-edged right.

```json
"arrows": [ { "from": "**Text must finish before speech starts.**", "to": "**Parallel generation** — …" } ]
```

### chips — keywords, grouped

```json
"chips": [
  { "label": "Architecture", "items": [ { "t": "SNAC codec", "key": true }, "8 sub-LM heads" ] }
]
```

`key: true` accents the term. Group by architecture / mechanism / data / framing
so the slide teaches structure, not just vocabulary.

### stats — a row of headline numbers

```json
"stats": [ { "v": "8 per step", "k": "one text token plus seven SNAC layers", "tone": "good" } ]
```

### callout — one or more highlighted notes

```json
"callout": [ { "tag": "Why it matters", "text": "…", "tone": "warn" } ]
```

### toc — the explained table of contents

```json
"toc": [ { "n": "1", "t": "The latency wall", "d": "Why cascaded systems cannot answer instantly." } ]
```

`d` is the *what you'll learn here* line. Writing these well is most of what
makes a deck feel like a course rather than a summary.

## Special slide types

### cover

```json
{ "id": "s01", "type": "cover", "kicker": "Paper walkthrough",
  "title": "Full paper title", "lead": "The thesis in one sentence.",
  "meta": [ { "k": "Authors", "v": "…" }, { "k": "arXiv", "v": "…" } ] }
```

### analogy

```json
{ "id": "s13", "type": "analogy", "kicker": "5 · Core algorithm", "icon": "🎼",
  "metaphor": "Delay decoding is a *round*, like Row Row Row Your Boat…",
  "map": [ { "from": "The lead voice", "to": "the text head — it sets what is said" } ],
  "foot": "Where it breaks: the offset here is fixed, not adaptive." }
```

`metaphor` is the picture. `map` connects it to the mechanism, three or four
pairs. `foot` is where you say where the analogy stops being true — include it.

### divider

```json
{ "id": "s09", "type": "divider", "num": "2", "title": "The method", "lead": "…" }
```

## Inline formatting

In any text field: `**bold**`, `` `code` ``, `*accent*` (renders in the accent
colour, useful for the paper's own wording). HTML is escaped, so these are the
only markup available — and narration scripts must use none of them.

## Diagrams

```json
"mermaid": "flowchart TB\n  A[\"Waveform\"] --> B[\"SNAC encoder\"]\n  B --> C[\"7 token layers\"]",
"vizcap": "optional caption under the diagram"
```

- Quote every node label: `A["Whisper encoder (frozen)"]`. Parentheses and
  slashes break unquoted labels.
- `<br/>` inside a label wraps it.
- Mindmaps are indentation-based and must not contain `-->`:
  ```
  mindmap
    root((Mini-Omni))
      Problem
        Cascade latency
  ```
- A slide takes either `mermaid` or `figure`, never both.

## Figures

```json
"figure": { "pdf": "mini-omni.pdf", "page": 5, "rect": [104, 68, 508, 278],
            "cap": "Figure 2 — …", "zoom": 2.0 }
```

`page` is 1-based; `rect` is `[x0, y0, x1, y1]` in PDF points, omitted for the
whole page. The build crops and base64-inlines it, so the HTML stays
self-contained. Find rects with `slides_build.py --figscan <pdf> [page]`, and
render your crop and look at it before committing — see SKILL.md.

Quote the paper's real caption, or make clear the wording is yours.

## Worked example

```json
{
  "id": "s14",
  "type": "mechanism",
  "kicker": "6 · Core algorithm",
  "title": "Batch parallel decoding — the paper's key trick",
  "layout": "split",
  "bullets": [
    { "h": "The problem", "t": "Audio answers reason worse than text answers." },
    { "h": "The move", "t": "Expand one input to **batch size 2**: A does text+audio, B text only." },
    { "h": "The swap", "t": "A's text token is **discarded**; B's is embedded into A's text positions." },
    { "h": "The payoff", "t": "A's audio is generated from B's stronger text." }
  ],
  "mermaid": "flowchart TB\n  Q[\"One user question\"] --> A[\"Sample A<br/>text + audio\"]\n  Q --> B[\"Sample B<br/>text only\"]\n  A --> AT[\"A's text token\"]\n  AT --> X[\"discarded\"]\n  B --> BT[\"B's text token\"]\n  BT --> INJ[\"embedded into A\"]\n  INJ --> OUT[\"Spoken answer with<br/>text-grade reasoning\"]",
  "script": "Here is the paper's cleverest move, and it starts with an admission. …"
}
```

## Budgets

The validator warns past these. They are what keeps a slide inside its 720 px
box, and they are deliberately tight — a slide that needs more is two slides.

| | limit |
|---|---|
| bullets per slide | 7 |
| characters per bullet | 165 |
| cards | 3 |
| arrow rows | 5 |
| table rows | 9 |
| chips per group | 10 |
| mindmap nodes | ~26 |
| flowchart nodes | ~10 |
| narration words | 105–205 |
