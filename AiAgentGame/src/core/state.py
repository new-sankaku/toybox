"""
State definitions for the AI Agent Game Creator system.
"""

from typing import TypedDict, Optional, Annotated
from enum import Enum
import operator


class Phase(str, Enum):
    """Current phase of the game development process."""
    PLANNING = "planning"
    CODING = "coding"
    ASSET_GENERATION = "asset_generation"
    TESTING = "testing"
    DEBUGGING = "debugging"
    COMPLETED = "completed"
    CANCELLED = "cancelled"


class DevelopmentPhase(str, Enum):
    """Development phase according to 4-phase approach."""
    MOCK = "mock"           # Step 1: Fastest iteration with placeholders
    GENERATE = "generate"   # Step 2: Real assets and basic implementation
    POLISH = "polish"       # Step 3: Quality improvements
    FINAL = "final"         # Step 4: Production quality


class ArtifactStatus(str, Enum):
    """Status of an artifact (code, image, audio, etc.)."""
    PENDING = "pending"
    IN_PROGRESS = "in_progress"
    COMPLETED = "completed"
    NEEDS_REVISION = "needs_revision"
    APPROVED = "approved"


class Artifact(TypedDict):
    """Represents a generated artifact."""
    id: str
    type: str              # "image", "audio", "code", "ui"
    agent: str             # Agent that generated this
    file_path: str         # Output file path
    status: ArtifactStatus
    feedback_history: list[dict]


class Task(TypedDict):
    """Represents a task to be executed."""
    id: str
    type: str              # "code", "visual", "audio", "ui"
    description: str
    assigned_agent: str
    status: str
    dependencies: list[str]  # Task IDs this depends on


class GameSpec(TypedDict):
    """Game specification."""
    title: str
    genre: str
    description: str
    mechanics: list[str]
    visual_style: str
    audio_style: str
    target_platform: str   # "pygame", "html5", "pyxel"


class Feedback(TypedDict):
    """User feedback on an artifact."""
    artifact_id: str       # Target artifact ID
    action: str            # "approve", "redo", "fix", "comment"
    comment: str           # User comment
    timestamp: float
    processed: bool


class Attribution(TypedDict):
    """Attribution information for assets."""
    asset_id: str           # Target asset ID
    asset_type: str         # "image", "audio", "font", "icon"
    source_type: str        # "free_asset", "generated", "purchased"

    # For free assets
    source_url: str         # Source URL
    source_name: str        # Site name (e.g., "OpenGameArt.org")
    author: str             # Author name
    license: str            # License type (e.g., "CC0", "CC-BY-4.0")
    license_url: str        # License full text URL
    requires_credit: bool   # Whether credit is required
    credit_text: str        # Credit text if required

    # Meta information
    downloaded_at: str      # Download timestamp
    notes: str              # Additional notes


class ClaudeCodeTask(TypedDict):
    """Task to be delegated to Claude Code."""
    task_id: str            # Task ID
    task_type: str          # "refactor", "debug", "test", "review"
    description: str        # Task description
    target_files: list[str] # Target file paths
    context: str            # Additional context
    priority: str           # "high", "medium", "low"
    created_at: str
    status: str             # "pending", "in_progress", "completed", "failed"


class ClaudeCodeResult(TypedDict):
    """Result from Claude Code execution."""
    task_id: str            # Corresponding task ID
    success: bool
    modified_files: list[str]
    summary: str            # Summary of execution
    errors: list[str]       # Errors if any
    completed_at: str


class LLMConfig(TypedDict, total=False):
    """LLM configuration override."""
    model: str
    temperature: float
    max_tokens: int
    provider: str


class GameState(TypedDict):
    """
    Main state object for the LangGraph workflow.
    Uses Annotated with operator.add for list fields to enable proper state updates.
    """
    # User input
    user_request: str
    development_phase: DevelopmentPhase

    # Planning
    game_spec: Optional[GameSpec]
    tasks: Annotated[list[Task], operator.add]

    # Artifacts
    artifacts: dict[str, Artifact]
    code_files: dict[str, str]

    # Review & Testing
    review_comments: Annotated[list[dict], operator.add]
    test_results: Optional[dict]
    errors: Annotated[list[dict], operator.add]

    # Control
    current_phase: Phase
    iteration: int
    review_iteration: int

    # Feedback
    pending_feedback: Annotated[list[Feedback], operator.add]

    # Attribution
    attributions: Annotated[list[Attribution], operator.add]

    # Claude Code delegation
    claude_code_tasks: Annotated[list[ClaudeCodeTask], operator.add]
    claude_code_results: Annotated[list[ClaudeCodeResult], operator.add]

    # Messages for agent communication
    messages: Annotated[list[dict], operator.add]

    # LLM configuration override
    llm_config: Optional[LLMConfig]


def create_initial_state(
    user_request: str,
    development_phase: DevelopmentPhase = DevelopmentPhase.MOCK,
    llm_config: Optional[LLMConfig] = None
) -> GameState:
    """Create initial state for a new game development session."""
    return GameState(
        user_request=user_request,
        development_phase=development_phase,
        game_spec=None,
        tasks=[],
        artifacts={},
        code_files={},
        review_comments=[],
        test_results=None,
        errors=[],
        current_phase=Phase.PLANNING,
        iteration=0,
        review_iteration=0,
        pending_feedback=[],
        attributions=[],
        claude_code_tasks=[],
        claude_code_results=[],
        messages=[],
        llm_config=llm_config
    )
