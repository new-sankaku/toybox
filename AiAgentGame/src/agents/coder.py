"""
Coder Agent - Game code implementation.
"""

import json
from pathlib import Path
from typing import Dict, Any
from langchain_core.prompts import ChatPromptTemplate

from ..core.state import GameState, DevelopmentPhase
from ..core.llm import get_llm_for_agent
from ..tools import ClaudeCodeDelegate, FileTools


class CoderAgent:
    """
    Coder Agent implements game code based on specifications.

    Responsibilities:
    - Generate game code based on spec
    - Adapt implementation to development phase
    - Write code files to output directory
    - Handle platform-specific implementations
    - Delegate complex tasks to Claude Code
    """

    def __init__(self):
        """Initialize the Coder Agent."""
        self.llm = get_llm_for_agent("coder")
        self.output_dir = Path("output/code")
        self.output_dir.mkdir(parents=True, exist_ok=True)
        self.claude_delegate = ClaudeCodeDelegate()
        self.file_tools = FileTools()

    def run(self, state: GameState) -> Dict[str, Any]:
        """
        Execute coding phase.

        Args:
            state: Current game state

        Returns:
            Dictionary with code_files
        """
        game_spec = state.get("game_spec")
        development_phase = state["development_phase"]

        if not game_spec:
            print("❌ No game spec available")
            return {"code_files": {}}

        print(f"💻 Implementing: {game_spec.get('title')}")
        print(f"🎮 Platform: {game_spec.get('target_platform')}")
        print(f"🔧 Phase: {development_phase}")

        # Check if task should be delegated to Claude Code
        if self._should_delegate(game_spec, development_phase):
            return self._delegate_to_claude_code(game_spec, development_phase, state)

        # Generate code based on platform
        platform = game_spec.get("target_platform", "pygame")

        if platform == "pygame":
            code_files = self._generate_pygame_code(game_spec, development_phase)
        elif platform == "pyxel":
            code_files = self._generate_pyxel_code(game_spec, development_phase)
        elif platform == "html5":
            code_files = self._generate_html5_code(game_spec, development_phase)
        else:
            print(f"⚠️  Unknown platform: {platform}, defaulting to pygame")
            code_files = self._generate_pygame_code(game_spec, development_phase)

        # Write files to output directory
        self._write_code_files(code_files)

        print(f"\n✅ Generated {len(code_files)} code files")
        for filename in code_files.keys():
            print(f"   📄 {filename}")

        return {"code_files": code_files}

    def _generate_pygame_code(
        self,
        game_spec: Dict[str, Any],
        development_phase: DevelopmentPhase
    ) -> Dict[str, str]:
        """Generate Pygame code."""

        phase_instructions = {
            DevelopmentPhase.MOCK: """
MOCK PHASE - Fastest implementation:
- Use pygame.draw for all graphics (rectangles, circles)
- Hardcode all values directly in the code
- Minimal error handling (basic try-except)
- Use TODO comments for future improvements
- Keep it simple - one main game loop
""",
            DevelopmentPhase.GENERATE: """
GENERATE PHASE - Real implementation:
- Load images/sounds from files (if available)
- Use config dictionary for settings
- Proper game state management
- Basic class structure
""",
            DevelopmentPhase.POLISH: """
POLISH PHASE - Quality code:
- Clean class architecture
- Separate concerns (Player, Enemy, etc.)
- Config file support
- Error handling and logging
""",
            DevelopmentPhase.FINAL: """
FINAL PHASE - Production code:
- Full OOP design
- Complete error handling
- Documentation and comments
- Performance optimization
"""
        }

        prompt = ChatPromptTemplate.from_template("""You are an expert Pygame developer.
Create a complete, working Pygame game based on the specification.

{phase_instructions}

Game Specification:
Title: {title}
Genre: {genre}
Description: {description}
Mechanics: {mechanics}
Visual Style: {visual_style}

Create a complete main.py file that:
1. Implements all specified mechanics
2. Is appropriate for the {development_phase} phase
3. Runs without errors
4. Includes clear comments

Return ONLY the Python code, no markdown formatting or explanations.
Start directly with imports.""")

        chain = prompt | self.llm

        try:
            code = chain.invoke({
                "phase_instructions": phase_instructions.get(development_phase, ""),
                "title": game_spec.get("title"),
                "genre": game_spec.get("genre"),
                "description": game_spec.get("description"),
                "mechanics": ", ".join(game_spec.get("mechanics", [])),
                "visual_style": game_spec.get("visual_style"),
                "development_phase": development_phase
            })

            # Extract code from response
            code_content = code.content if hasattr(code, 'content') else str(code)

            # Clean up markdown formatting if present
            code_content = self._clean_code_output(code_content)

            return {
                "main.py": code_content,
                "README.md": self._generate_readme(game_spec)
            }

        except Exception as e:
            print(f"❌ Error generating code: {e}")
            return {
                "main.py": self._generate_fallback_pygame_code(game_spec),
                "README.md": self._generate_readme(game_spec)
            }

    def _generate_pyxel_code(
        self,
        game_spec: Dict[str, Any],
        development_phase: DevelopmentPhase
    ) -> Dict[str, str]:
        """Generate Pyxel code (retro game engine)."""
        # Similar to pygame but for Pyxel
        # Simplified for now
        return {
            "main.py": f"""# {game_spec.get('title')}
# Pyxel implementation - TODO

import pyxel

class Game:
    def __init__(self):
        pyxel.init(160, 120, title="{game_spec.get('title')}")
        self.x = 0
        pyxel.run(self.update, self.draw)

    def update(self):
        if pyxel.btn(pyxel.KEY_RIGHT):
            self.x = min(self.x + 2, 150)
        if pyxel.btn(pyxel.KEY_LEFT):
            self.x = max(self.x - 2, 0)

    def draw(self):
        pyxel.cls(0)
        pyxel.rect(self.x, 50, 10, 10, 11)

Game()
""",
            "README.md": self._generate_readme(game_spec)
        }

    def _generate_html5_code(
        self,
        game_spec: Dict[str, Any],
        development_phase: DevelopmentPhase
    ) -> Dict[str, str]:
        """Generate HTML5 Canvas code."""
        return {
            "index.html": f"""<!DOCTYPE html>
<html>
<head>
    <title>{game_spec.get('title')}</title>
    <style>
        body {{ margin: 0; display: flex; justify-content: center; align-items: center; height: 100vh; background: #222; }}
        canvas {{ border: 1px solid #fff; }}
    </style>
</head>
<body>
    <canvas id="gameCanvas" width="800" height="600"></canvas>
    <script src="game.js"></script>
</body>
</html>
""",
            "game.js": """// Game implementation
const canvas = document.getElementById('gameCanvas');
const ctx = canvas.getContext('2d');

let x = 50, y = 50;

function update() {
    // Game logic here
}

function draw() {
    ctx.fillStyle = '#222';
    ctx.fillRect(0, 0, canvas.width, canvas.height);

    ctx.fillStyle = '#0f0';
    ctx.fillRect(x, y, 50, 50);
}

function gameLoop() {
    update();
    draw();
    requestAnimationFrame(gameLoop);
}

gameLoop();
""",
            "README.md": self._generate_readme(game_spec)
        }

    def _generate_fallback_pygame_code(self, game_spec: Dict[str, Any]) -> str:
        """Generate minimal fallback Pygame code."""
        return f'''"""
{game_spec.get("title", "Game")}
{game_spec.get("description", "")}
"""

import pygame
import sys

# Initialize Pygame
pygame.init()

# Constants
SCREEN_WIDTH = 800
SCREEN_HEIGHT = 600
FPS = 60

# Colors
WHITE = (255, 255, 255)
BLACK = (0, 0, 0)
GREEN = (0, 255, 0)

# Create screen
screen = pygame.display.set_mode((SCREEN_WIDTH, SCREEN_HEIGHT))
pygame.display.set_caption("{game_spec.get("title", "Game")}")
clock = pygame.time.Clock()

# Game variables
player_x = SCREEN_WIDTH // 2
player_y = SCREEN_HEIGHT // 2
player_speed = 5

# Game loop
running = True
while running:
    # Handle events
    for event in pygame.event.get():
        if event.type == pygame.QUIT:
            running = False

    # Get keys
    keys = pygame.key.get_pressed()
    if keys[pygame.K_LEFT]:
        player_x -= player_speed
    if keys[pygame.K_RIGHT]:
        player_x += player_speed
    if keys[pygame.K_UP]:
        player_y -= player_speed
    if keys[pygame.K_DOWN]:
        player_y += player_speed

    # Draw
    screen.fill(BLACK)
    pygame.draw.rect(screen, GREEN, (player_x, player_y, 50, 50))

    pygame.display.flip()
    clock.tick(FPS)

pygame.quit()
sys.exit()
'''

    def _generate_readme(self, game_spec: Dict[str, Any]) -> str:
        """Generate README for the game."""
        return f"""# {game_spec.get('title', 'Game')}

## Description
{game_spec.get('description', 'A game created by AI Agent Game Creator')}

## Genre
{game_spec.get('genre', 'N/A')}

## How to Run

### Requirements
- Python 3.10+
- {game_spec.get('target_platform', 'pygame')}

### Installation
```bash
pip install {game_spec.get('target_platform', 'pygame')}
```

### Run
```bash
python main.py
```

## Game Mechanics
{chr(10).join(f'- {m}' for m in game_spec.get('mechanics', []))}

## Visual Style
{game_spec.get('visual_style', 'Simple')}

## Audio Style
{game_spec.get('audio_style', 'Minimal')}

---
*Generated by AI Agent Game Creator*
"""

    def _clean_code_output(self, code: str) -> str:
        """Clean up code output from LLM."""
        # Remove markdown code blocks if present
        if code.startswith("```"):
            lines = code.split("\n")
            # Remove first line (```python or similar)
            lines = lines[1:]
            # Remove last line if it's ```
            if lines and lines[-1].strip() == "```":
                lines = lines[:-1]
            code = "\n".join(lines)

        return code.strip()

    def _write_code_files(self, code_files: Dict[str, str]) -> None:
        """Write code files to output directory."""
        for filename, content in code_files.items():
            file_path = self.output_dir / filename
            with open(file_path, 'w', encoding='utf-8') as f:
                f.write(content)
            print(f"   ✍️  Wrote {file_path}")

    def _should_delegate(self, game_spec: Dict[str, Any], phase: DevelopmentPhase) -> bool:
        """
        Determine if implementation should be delegated to Claude Code.

        Args:
            game_spec: Game specification
            phase: Development phase

        Returns:
            True if should delegate
        """
        # Estimate complexity
        mechanics_count = len(game_spec.get("mechanics", []))
        estimated_lines = mechanics_count * 50  # Rough estimate

        # More complex in later phases
        phase_multipliers = {
            DevelopmentPhase.MOCK: 1.0,
            DevelopmentPhase.GENERATE: 1.5,
            DevelopmentPhase.POLISH: 2.0,
            DevelopmentPhase.FINAL: 2.5
        }
        estimated_lines *= phase_multipliers.get(phase, 1.0)

        # Check delegation criteria
        should_delegate = self.claude_delegate.should_delegate(
            estimated_lines=int(estimated_lines),
            file_count=1,
            complexity_score=mechanics_count / 10.0,  # Normalize
            task_type="code_generation"
        )

        return should_delegate

    def _delegate_to_claude_code(
        self,
        game_spec: Dict[str, Any],
        phase: DevelopmentPhase,
        state: GameState
    ) -> Dict[str, Any]:
        """
        Delegate code generation to Claude Code.

        Args:
            game_spec: Game specification
            phase: Development phase
            state: Current state

        Returns:
            Dictionary with code_files or empty if delegation
        """
        description = f"""Generate a complete {game_spec.get('target_platform')} game:

Title: {game_spec.get('title')}
Genre: {game_spec.get('genre')}
Description: {game_spec.get('description')}

Mechanics:
{chr(10).join(f'- {m}' for m in game_spec.get('mechanics', []))}

Development Phase: {phase}

Requirements:
- Create main.py with complete game implementation
- Follow {phase} phase guidelines (see ARCHITECTURE.md)
- Include README.md with instructions
- Ensure code runs without errors

Output files to: output/code/
"""

        # Create task
        task, result = self.claude_delegate.create_task(
            task_type="code_generation",
            description=description,
            target_files=["output/code/main.py", "output/code/README.md"],
            context=f"Game spec: {json.dumps(game_spec, indent=2)}",
            priority="high",
            wait_for_result=False  # Don't block workflow
        )

        # Add task to state
        state["claude_code_tasks"].append(task)

        print("   ⏭️  Continuing with fallback implementation while waiting...")

        # Return empty for now - Claude Code will handle it
        return {"code_files": {}}
