#!/usr/bin/env python3
"""
AI Agent Game Creator - Main Entry Point

Usage:
    python -m src.main "Create a simple platformer game"
    python -m src.main --help
"""

import sys
import argparse
from pathlib import Path

# Add project root to path
project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))

from src.core.state import create_initial_state, DevelopmentPhase
from src.core.graph import GameCreatorGraph


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

    # Print welcome message
    print("\n" + "=" * 80)
    print("🎮 AI AGENT GAME CREATOR")
    print("=" * 80)
    print(f"Request: {args.request}")
    print(f"Phase: {args.phase}")
    print(f"Output: {args.output}")
    print("=" * 80 + "\n")

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
        attribution.print_summary()

        # Print summary
        print("\n" + "=" * 80)
        print("📊 SUMMARY")
        print("=" * 80)

        game_spec = final_state.get("game_spec", {})
        print(f"Title: {game_spec.get('title', 'N/A')}")
        print(f"Genre: {game_spec.get('genre', 'N/A')}")
        print(f"Platform: {game_spec.get('target_platform', 'N/A')}")
        print(f"\nCode Files: {len(final_state.get('code_files', {}))}")
        print(f"Assets: {len(final_state.get('artifacts', {}))}")
        print(f"Errors: {len(final_state.get('errors', []))}")

        print("\n📂 Output Location:")
        print(f"   Code: {args.output}/code/")
        print(f"   Images: {args.output}/images/")
        print(f"   Audio: {args.output}/audio/")
        print(f"   UI: {args.output}/ui/")

        if final_state.get("current_phase") == "completed":
            print("\n✅ Game creation completed successfully!")
            print("\n🎮 To run your game:")
            print(f"   cd {args.output}/code")
            print("   python main.py")
        else:
            print("\n⚠️  Game creation incomplete")
            if final_state.get("errors"):
                print("   Please check errors above")

        print("=" * 80 + "\n")

        return 0

    except KeyboardInterrupt:
        print("\n\n⚠️  Interrupted by user")
        return 1

    except Exception as e:
        print(f"\n\n❌ Error: {e}")
        import traceback
        traceback.print_exc()
        return 1


if __name__ == "__main__":
    sys.exit(main())
