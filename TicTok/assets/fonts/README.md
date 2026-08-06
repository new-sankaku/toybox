# Burn-in fonts

Two groups live here, fetched by the same module (`tictok/record/fonts.py`) but with
different failure behaviour:

* **Comment-overlay fonts** (`FONT_MANIFEST`) — colour emoji and glyph fallbacks for
  the Pillow comment layer. A fetch failure degrades to the monochrome ASS path.
* **Telop fonts** (`TELOP_FONT_MANIFEST`) — the typefaces behind the subtitle style
  presets in `tictok/record/telop_styles.py`. A fetch failure **stops the burn-in**:
  substituting a different typeface would silently produce a permanent artifact in a
  style the user did not choose.

## Comment-overlay fonts

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
| `NotoSansSymbols2-Regular.ttf` | Fallback: dingbats / ornaments (e.g. U+275B) and misc symbols the emoji font has no colour glyph for | [google/fonts · notosanssymbols2](https://github.com/google/fonts/tree/main/ofl/notosanssymbols2) | SIL OFL 1.1 |
| `unifont.otf` | Universal last resort: any assigned BMP codepoint (exotic scripts kaomoji borrow — Canadian syllabics, Thai, Yi, Armenian, Ethiopic, …) so nothing is silently dropped | [GNU Unifont](https://unifoundry.com/unifont/) | GPLv2+FE / SIL OFL 1.1 |

The SIL Open Font License (Version 1.1) text is in `OFL.txt`.

The fallback fonts cover decorative glyphs the primary CJK font lacks (kaomoji often
use Georgian / phonetic / maths characters as eyes, brows and mouths). PIL has no
automatic font fallback, so `video_overlay.py` reads each font's cmap (via fontTools)
and routes every character to the first font that has a glyph for it; characters no
bundled font covers — and invisible bidi/format controls — are stripped so the
burn-in never shows replacement boxes (tofu).

If these files are missing, comments still render via the monochrome ASS path
(emoji appear black/white) — the layer is skipped and logged, not an error.

## Telop fonts

These live under `telop/`, **one directory per typeface** (`telop/ReggaeOne-Regular/…`).
libass reads *every file* in the directory given to `fontsdir`, so a shared directory
made each ffmpeg process load every bundled typeface plus unifont (16 MB) and the
colour-emoji font it has no use for, and put `Error opening memory font 'README.md'`
in every burn-in log. One typeface per directory means exactly the one in use is read.

The subtitle burn-in draws through libass, which is pointed at the selected preset's
directory with the `ass` filter's `fontsdir` so the typeface is the same on every
machine. Without it
libass resolves the style's family through the host's font configuration — on this
Windows machine `Sans` lands on Arial + Yu Gothic UI Semibold, which is not what the
presets are designed around.

The family name in each preset is the name **libass matches**, which is not always the
Google Fonts family name — `Shippori Mincho B1 ExtraBold` does not match under
`Shippori Mincho B1`. The names in `telop_styles.py` were confirmed from libass's own
`fontselect:` log lines; do not guess them.

| File (under `telop/<stem>/`) | Preset | Source | License |
|------|--------|--------|---------|
| `NotoSansCJKjp-Bold.otf` | 通常 / ネオン / ニュース帯 / 海外ニュース / 配信字幕 / スポーツ中継 / グリッチ | [notofonts/noto-cjk](https://github.com/notofonts/noto-cjk) | SIL OFL 1.1 |
| `NotoSansCJKjp-Regular.otf` | ミニマル（同じ file が comment 側にもあるが、`fontsdir` が別なので両方に要る） | [notofonts/noto-cjk](https://github.com/notofonts/noto-cjk) | SIL OFL 1.1 |
| `ReggaeOne-Regular.ttf` | バラエティ | [google/fonts · reggaeone](https://github.com/google/fonts/tree/main/ofl/reggaeone) | SIL OFL 1.1 |
| `MochiyPopOne-Regular.ttf` | カワイイ | [google/fonts · mochiypopone](https://github.com/google/fonts/tree/main/ofl/mochiypopone) | SIL OFL 1.1 |
| `ShipporiMinchoB1-ExtraBold.ttf` | ホラー | [google/fonts · shipporiminchob1](https://github.com/google/fonts/tree/main/ofl/shipporiminchob1) | SIL OFL 1.1 |
| `DotGothic16-Regular.ttf` | レトロ | [google/fonts · dotgothic16](https://github.com/google/fonts/tree/main/ofl/dotgothic16) | SIL OFL 1.1 |
| `ShipporiMincho-Regular.ttf` | 映画字幕 | [google/fonts · shipporimincho](https://github.com/google/fonts/tree/main/ofl/shipporimincho) | SIL OFL 1.1 |
| `YuseiMagic-Regular.ttf` | 手書き | [google/fonts · yuseimagic](https://github.com/google/fonts/tree/main/ofl/yuseimagic) | SIL OFL 1.1 |
| `HachiMaruPop-Regular.ttf` | ゆるふわ | [google/fonts · hachimarupop](https://github.com/google/fonts/tree/main/ofl/hachimarupop) | SIL OFL 1.1 |
| `YujiSyuku-Regular.ttf` | 和風 | [google/fonts · yujisyuku](https://github.com/google/fonts/tree/main/ofl/yujisyuku) | SIL OFL 1.1 |
| `RocknRollOne-Regular.ttf` | インパクト / アメコミ | [google/fonts · rocknrollone](https://github.com/google/fonts/tree/main/ofl/rocknrollone) | SIL OFL 1.1 |
| `TrainOne-Regular.ttf` | サイバー | [google/fonts · trainone](https://github.com/google/fonts/tree/main/ofl/trainone) | SIL OFL 1.1 |
| `ZenMaruGothic-Bold.ttf` | ポップ | [google/fonts · zenmarugothic](https://github.com/google/fonts/tree/main/ofl/zenmarugothic) | SIL OFL 1.1 |

Only the preset actually in use is fetched (a burn-in downloads its own typeface on
first use); `scripts/download_fonts.py` pre-fetches all of them.

The settings screen shows a sample image per preset, rendered through this same libass
path by `tictok/record/telop_preview.py` and cached under the work root — not drawn in
CSS, so the sample cannot drift from what actually gets burned in.
