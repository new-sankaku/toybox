#!/usr/bin/env python3
"""
AI Agent Game Creator - Main Entry Point

Usage:
    python -m src.main "Create a simple platformer game"
    python -m src.main --help
"""

import sys
import io
import argparse
from pathlib import Path

# Fix Windows console encoding for Unicode support
if sys.platform == "win32":
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')
    sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding='utf-8', errors='replace')

# Add project root to path
project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))

# Load environment variables from .env file
from dotenv import load_dotenv
load_dotenv(project_root / ".env")

from src.core.state import create_initial_state, DevelopmentPhase, Phase
from src.core.graph import GameCreatorGraph
from src.utils.logger import setup_logger

logger = setup_logger()


def main():
    """Main entry point for AI Agent Game Creator."""

    parser = argparse.ArgumentParser(
        description="AI Agent Game Creator - Create games with AI agents",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  python -m src.main "Create a simple platformer game"
  python -m src.main "Make a space shooter" --phase generate
  python -m src.main "Create a puzzle game" --phase mock

Development Phases:
  mock     - Fastest iteration with placeholders (default)
  generate - Real assets and basic implementation
  polish   - Quality improvements and refinement
  final    - Production-ready quality
        """
    )

    parser.add_argument(
        "request",
        type=str,
        help="Game creation request (e.g., 'Create a platformer game')"
    )

    parser.add_argument(
        "--phase",
        type=str,
        choices=["mock", "generate", "polish", "final"],
        default="mock",
        help="Development phase (default: mock)"
    )

    parser.add_argument(
        "--output",
        type=str,
        default="output",
        help="Output directory (default: output)"
    )

    args = parser.parse_args()

    # Convert phase string to enum
    phase_map = {
        "mock": DevelopmentPhase.MOCK,
        "generate": DevelopmentPhase.GENERATE,
        "polish": DevelopmentPhase.POLISH,
        "final": DevelopmentPhase.FINAL
    }

    development_phase = phase_map[args.phase]

    logger.info("AI Agent Game Creator 開始")
    logger.info(f"リクエスト: {args.request}")
    logger.info(f"フェーズ: {args.phase}")
    logger.info(f"出力先: {args.output}")

    # Create initial state
    state = create_initial_state(
        user_request=args.request,
        development_phase=development_phase
    )

    # Create and run graph
    try:
        graph = GameCreatorGraph()
        final_state = graph.run(state)

        # Generate attribution credits
        from src.tools import AttributionManager
        attribution = AttributionManager()
        attribution.generate_credits_file("output/CREDITS.md")

        # Print summary
        game_spec = final_state.get("game_spec", {})
        logger.info("結果:")
        logger.info(f"  タイトル: {game_spec.get('title', 'N/A')}")
        logger.info(f"  ジャンル: {game_spec.get('genre', 'N/A')}")
        logger.info(f"  プラットフォーム: {game_spec.get('target_platform', 'N/A')}")
        logger.info(f"  コードファイル: {len(final_state.get('code_files', {}))}件")
        logger.info(f"  アセット: {len(final_state.get('artifacts', {}))}件")
        logger.info(f"  エラー: {len(final_state.get('errors', []))}件")

        current_phase = final_state.get("current_phase")
        if current_phase == Phase.COMPLETED:
            logger.info("ゲーム作成完了")
            logger.info(f"実行: cd {args.output}/code && python main.py")
        else:
            logger.warning(f"ゲーム作成未完了 (フェーズ: {current_phase})")

        return 0

    except KeyboardInterrupt:
        logger.warning("ユーザーによる中断")
        return 1

    except Exception as e:
        logger.error(f"エラー: {e}")
        import traceback
        traceback.print_exc()
        return 1


if __name__ == "__main__":
    sys.exit(main())
