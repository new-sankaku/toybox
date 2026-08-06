"""Pre-fetch the burn-in fonts into assets/fonts.

Two groups are fetched: the comment-overlay fonts (colour emoji + fallbacks) and
the telop fonts used by the subtitle style presets. Both are fetched on demand the
first time a burn-in needs them, so this script is optional -- it just does the
download up front (e.g. to warm an offline environment) and reports the result.
Each font is verified against its pinned SHA-256; a mismatch or network error exits
non-zero.

Usage (run from the TicTok directory):
    python scripts/download_fonts.py            # fetch any missing/stale fonts
    python scripts/download_fonts.py --force    # re-download all fonts
"""

from __future__ import annotations

import argparse
import logging
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from tictok.record.fonts import (  # noqa: E402
    FONT_DIR, FONT_MANIFEST, TELOP_FONT_MANIFEST, ensure_fonts, ensure_telop_font,
    telop_font_dir,
)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--force", action="store_true", help="re-download every font")
    args = parser.parse_args()

    logging.basicConfig(level=logging.INFO, format="%(message)s")
    log = logging.getLogger("tictok.fonts")
    try:
        ensure_fonts(force=args.force)
    except Exception:
        log.error("commentのfontのdownloadに失敗しました", exc_info=True)
        return 1
    print(f"All {len(FONT_MANIFEST)} comment-overlay fonts present in {FONT_DIR}")
    for name in TELOP_FONT_MANIFEST:
        if args.force:
            (telop_font_dir(name) / name).unlink(missing_ok=True)
        try:
            ensure_telop_font(name)
        except Exception:
            log.error("テロップのfont %s のdownloadに失敗しました", name, exc_info=True)
            return 1
    print(f"All {len(TELOP_FONT_MANIFEST)} telop fonts present under {FONT_DIR / 'telop'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
