# Inside the bladeRF FPGA — guide sources

The source for a single-page technical guide to the bladeRF 2.0 micro's hosted FPGA image.
Published as a Claude Artifact:

**https://claude.ai/code/artifact/cd0df1ad-2556-428f-a75a-1b02b4236619**

Five chapters, one page, sticky chapter index down the left side, print styles so
Ctrl-P → Save as PDF gives a clean document.

| Ch | Title | Fragment | Section id prefix |
|----|-------|----------|-------------------|
| 01 | The Module Inventory | `ch1.frag.html` | `m1`…`m7` |
| 02 | The Round Trip | `ch2.frag.html` | `r1`…`r5` |
| 03 | The NIOS | `ch3.frag.html` | `n1`…`n7` |
| 04 | The TX FIFO | `ch4.frag.html` | `t1`…`t6` |
| 05 | The RX FIFO | `ch5.frag.html` | `x1`…`x6` |

`index.frag.html` holds the front-matter "Findings at a glance" and the closing
"How this was made". `base-head.html` is the shared `<style>` block (design tokens,
typography, component CSS). The single-page layout CSS and the scroll-spy script live
inside `build_guide.py`.

---

## Rebuild

```bash
cd docs/fpga-guide
python build_guide.py          # → fpga-guide.out.html
```

No dependencies beyond the Python standard library. The script fails loud on unbalanced
tags, unclosed SVG shapes, and nav/section count mismatches — **do not publish if it
aborts**, a malformed page publishes silently and renders wrong.

## Publish

Use the **Artifact** tool with `file_path` pointing at `fpga-guide.out.html` and
`url` set to the URL above, so it updates in place instead of creating a new artifact:

```
Artifact(file_path=".../fpga-guide.out.html",
         url="https://claude.ai/code/artifact/cd0df1ad-2556-428f-a75a-1b02b4236619",
         title="Inside the bladeRF FPGA",
         favicon="📡",
         description="...")
```

Keep the title and favicon stable across republishes — readers find the tab by its icon.

### Three stale pointer artifacts

Chapters 1–3 were briefly published as standalone pages before being merged. Those URLs
still exist and now serve short "this moved" pages pointing into the guide. They are not
built from anything here and normally need no maintenance. Leave them alone unless the
guide URL changes, in which case update the links inside them.

- `b4c106cb-eeac-4772-b14d-851694ea126c` (was Ch 1)
- `3c06de14-8517-47ef-a37c-776fc3831186` (was Ch 2)
- `79058fd7-079d-44d5-b0c4-e1b3cc12946c` (was Ch 3)

---

## Add a chapter

1. **Write `ch6.frag.html`.** It must contain **only top-level `<section>…</section>`
   blocks** — no wrapper div, no `<html>`, no `<style>`. The build regex is
   `<section>.*?</section>`, so a nested `<section>` will break it. Each section opens
   with `<h2>` and usually `<p class="sub">`.

2. **Add one entry to `CHAPTERS` in `build_guide.py`.** Pick an unused `prefix` letter.
   `nav` must have **exactly one label per `<section>`, in order** — the build aborts
   otherwise. `tally` takes exactly four `(value, label)` pairs.

3. Rebuild, check it says the chapter count you expect, publish with `url=`.

Nothing else needs editing. The sidebar, anchors, scroll-spy and print pagination are
all generated from that table.

## Edit an existing chapter

Edit its `chN.frag.html`, rebuild, republish. If you **add or remove a `<section>`**,
update that chapter's `nav` list to match or the build will abort — deliberately, since
a silent mismatch would misalign every sidebar link after it.

---

## House style

Content conventions the existing chapters follow. Worth matching.

- **Claims are traced, not remembered.** Every statement should be checkable against the
  bladeRF source. Where the source can't settle something, the chapters say so explicitly
  rather than guessing — several already do.
- **Lead with the surprising thing.** Chapters are organised around what a careful reader
  would get wrong, not around file layout.
- **Numbers over adjectives.** "6144 of 8192 words" beats "nearly full".
- No emoji in body text. No "as we saw earlier" — chapters are entered directly via anchors.

### CSS classes available

| Class | Use |
|---|---|
| `.sub` | mono subtitle under an `<h2>` |
| `h3.axis` | sub-heading inside a section |
| `.note` + `.note .h` | rust-bordered callout with a small caps header |
| `.mods` / `.mod` / `.mod-name` / `.mod-src` / `.mod-job` | the three-column item list |
| `.mod-src.nuand` / `.mod-src.adi` | coloured origin badges |
| `.stagerow` + `.sn` | numbered step heading |
| `.wires` | mono signal-name line under a step heading |
| `.scroller` > `<table>` | any table — required, or wide tables break the page |
| `.tbl-title` | small caps label above a table |
| `tr.hot` | highlighted table row |
| `td.num` | right-aligned tabular numerals |
| `<pre>` with `<b>`/`<i>` | code; `<b>` = emphasis, `<i>` = comment |

### Figures

Inline `<svg>` only — no libraries, no external images (the artifact CSP blocks them).

- Set `viewBox`, let CSS scale it. Give `role="img"` and a real `aria-label`.
- **Use `currentColor` for strokes and text**, and `var(--rust)` / `var(--indigo)` /
  `var(--slate)` for meaning. Never a hex literal — the page renders in both light and
  dark themes and a literal will be invisible in one of them.
- **Self-close every `<rect/> <line/> <path/>`** — the build checks this.
- Wrap in `<figure>` with a `<figcaption>` that states the figure's claim.
- Label arrows. An unlabelled arrow means "related somehow".

### Theming

The palette is CSS custom properties in `base-head.html`, defined three times: bare
`:root` (light), `@media (prefers-color-scheme: dark)` guarded with
`:root:not([data-theme="light"])`, and `:root[data-theme="dark"]`. **Never declare a
colour only inside a media or `[data-theme]` block** — it won't apply in the default
un-stamped state and the page will render one theme's text on the other's background.

---

## Provenance

Traced from `bladeRF @ 35174c30` — VHDL, Verilog, Qsys build scripts, FX3 firmware and
`.qip` build manifests. Local checkout at `~/vikram/bladeRF`.

Note `thirdparty/analogdevicesinc/no-OS` is an **unfetched submodule** there; the AD9361
driver is not on disk. Pinned commit is `0bba46e` if you need it.

**Nothing in the guide is measured on hardware.** Cycle counts come from state machines,
clock rates from timing constraints and deserializer geometry. Several open questions are
flagged as such in the text — leave them flagged unless you actually measure them.
