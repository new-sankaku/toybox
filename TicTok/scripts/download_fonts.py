"""Pre-fetch the comment-overlay fonts into assets/fonts.

The fonts (~30 MB) are fetched on demand the first time a recording burn-in needs
them, so this script is optional -- it just does that download up front (e.g. to
warm an offline environment) and reports the result. Each font is verified against
its pinned SHA-256; a mismatch or network error exits non-zero.

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

from tictok.record.fonts import FONT_DIR, FONT_MANIFEST, ensure_fonts  # noqa: E402


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--force", action="store_true", help="re-download every font")
    args = parser.parse_args()

    logging.basicConfig(level=logging.INFO, format="%(message)s")
    try:
        ensure_fonts(force=args.force)
    except Exception:
        logging.getLogger("tictok.fonts").error("fontのdownloadに失敗しました", exc_info=True)
        return 1
    print(f"All {len(FONT_MANIFEST)} comment-overlay fonts present in {FONT_DIR}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
