# Comment-overlay fonts

These fonts let the recording burn-in render comments with **colour emoji** (like
a phone) instead of the monochrome glyphs libass produces. Comments are drawn
through Pillow as a separate overlay layer (`video_overlay.py`), which needs the
font files on disk and has no automatic font fallback — so a CJK+Latin text font
and a colour-emoji font are used together.

They are **not committed** (~30 MB of binary). Instead they are fetched on demand
the first time a burn-in needs them, pinned by SHA-256, by `tictok/record/fonts.py`
— the sources and digests live in its `FONT_MANIFEST`. To pre-fetch them (e.g. for
an offline machine) run `python scripts/download_fonts.py`. If a fetch fails,
comments still render via the monochrome ASS path — the colour layer is skipped
and logged, not an error.

| File | Use | Source | License |
|------|-----|--------|---------|
| `NotoSansCJKjp-Regular.otf` | Comment text (Japanese / Latin / CJK) | [notofonts/noto-cjk](https://github.com/notofonts/noto-cjk) | SIL OFL 1.1 |
| `NotoColorEmoji.ttf` | Colour emoji in comments | [googlefonts/noto-emoji](https://github.com/googlefonts/noto-emoji) | SIL OFL 1.1 |
| `NotoSans-VF.ttf` | Fallback: phonetic-extension letters, combining marks | [google/fonts · notosans](https://github.com/google/fonts/tree/main/ofl/notosans) | SIL OFL 1.1 |
| `NotoSansGeorgian-VF.ttf` | Fallback: Georgian letters (used as kaomoji brows) | [google/fonts · notosansgeorgian](https://github.com/google/fonts/tree/main/ofl/notosansgeorgian) | SIL OFL 1.1 |
| `NotoSansMath-Regular.ttf` | Fallback: maths operators (used as kaomoji mouths) | [google/fonts · notosansmath](https://github.com/google/fonts/tree/main/ofl/notosansmath) | SIL OFL 1.1 |

The SIL Open Font License (Version 1.1) text is in `OFL.txt`.

The fallback fonts cover decorative glyphs the primary CJK font lacks (kaomoji often
use Georgian / phonetic / maths characters as eyes, brows and mouths). PIL has no
automatic font fallback, so `video_overlay.py` reads each font's cmap (via fontTools)
and routes every character to the first font that has a glyph for it; characters no
bundled font covers — and invisible bidi/format controls — are stripped so the
burn-in never shows replacement boxes (tofu).

If these files are missing, comments still render via the monochrome ASS path
(emoji appear black/white) — the layer is skipped and logged, not an error.
