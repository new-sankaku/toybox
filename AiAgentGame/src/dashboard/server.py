"""
Dashboard Server - FastAPI + WebSocket for real-time agent monitoring.
"""

import os
import sys
import asyncio
import threading
import json
import httpx
from pathlib import Path
from typing import Optional, Set

from fastapi import FastAPI, WebSocket, WebSocketDisconnect, BackgroundTasks
from fastapi.staticfiles import StaticFiles
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.middleware.cors import CORSMiddleware
import uvicorn

# Add project root to path
project_root = Path(__file__).parent.parent.parent
sys.path.insert(0, str(project_root))

from src.dashboard.tracker import tracker, AgentEvent, AgentStatus

# FastAPI app
app = FastAPI(title="AI Agent Game Creator Dashboard")

# Store event loop reference for cross-thread communication
main_loop = None

# CORS
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

# Static files
static_dir = Path(__file__).parent / "static"
static_dir.mkdir(exist_ok=True)
app.mount("/static", StaticFiles(directory=str(static_dir)), name="static")

# WebSocket connections
active_connections: Set[WebSocket] = set()

# Workflow state
workflow_running = False


async def broadcast_event(event: AgentEvent):
    """Broadcast event to all connected WebSocket clients."""
    message = json.dumps({"type": "agent_event", "data": event.to_dict()})
    disconnected = set()
    for ws in active_connections:
        try:
            await ws.send_text(message)
        except Exception:
            disconnected.add(ws)
    active_connections.difference_update(disconnected)


def sync_broadcast_event(event: AgentEvent):
    """Sync wrapper for broadcast_event - schedules on main loop."""
    global main_loop
    if main_loop and main_loop.is_running():
        asyncio.run_coroutine_threadsafe(broadcast_event(event), main_loop)


# Subscribe tracker to sync broadcast (works from any thread)
tracker.subscribe(sync_broadcast_event)


@app.on_event("startup")
async def startup_event():
    """Store event loop reference on startup."""
    global main_loop
    main_loop = asyncio.get_running_loop()


@app.get("/", response_class=HTMLResponse)
async def index():
    """Serve dashboard HTML."""
    html_path = static_dir / "dashboard.html"
    if html_path.exists():
        return HTMLResponse(content=html_path.read_text(encoding="utf-8"))
    return HTMLResponse(content="<h1>Dashboard not found. Run setup first.</h1>")


@app.websocket("/ws")
async def websocket_endpoint(websocket: WebSocket):
    """WebSocket endpoint for real-time updates."""
    await websocket.accept()
    active_connections.add(websocket)
    print(f"WebSocket connected. Total: {len(active_connections)}")

    # Send current state
    try:
        state_msg = json.dumps({"type": "state_update", "data": tracker.get_state()})
        await websocket.send_text(state_msg)
    except Exception:
        pass

    try:
        while True:
            # Keep connection alive, receive any messages
            data = await websocket.receive_text()
            # Could handle client messages here if needed
    except WebSocketDisconnect:
        pass
    finally:
        active_connections.discard(websocket)
        print(f"WebSocket disconnected. Total: {len(active_connections)}")


@app.get("/api/state")
async def get_state():
    """Get current workflow state."""
    return JSONResponse(content=tracker.get_state())


@app.get("/api/llm-config")
async def get_llm_config():
    """Get LLM configuration (providers and models from APIs)."""
    from dotenv import load_dotenv
    load_dotenv(project_root / ".env")

    providers = {}

    # Fetch Anthropic models
    anthropic_key = os.getenv("ANTHROPIC_API_KEY")
    if anthropic_key:
        try:
            async with httpx.AsyncClient() as client:
                response = await client.get(
                    "https://api.anthropic.com/v1/models",
                    headers={
                        "x-api-key": anthropic_key,
                        "anthropic-version": "2023-06-01"
                    },
                    timeout=10.0
                )
                if response.status_code == 200:
                    data = response.json()
                    models = []
                    for model in data.get("data", []):
                        model_id = model.get("id", "")
                        # Filter Claude models and get display name
                        if "claude" in model_id.lower():
                            display_name = get_claude_display_name(model_id)
                            max_tokens = get_model_max_tokens(model_id)
                            models.append({
                                "id": model_id,
                                "name": display_name,
                                "max_tokens": max_tokens
                            })
                    # Sort by name (newer models first)
                    models.sort(key=lambda x: x["name"], reverse=True)
                    providers["anthropic"] = {"models": models}
        except Exception as e:
            print(f"Failed to fetch Anthropic models: {e}")

    # Fetch OpenAI models
    openai_key = os.getenv("OPENAI_API_KEY")
    if openai_key:
        try:
            async with httpx.AsyncClient() as client:
                response = await client.get(
                    "https://api.openai.com/v1/models",
                    headers={"Authorization": f"Bearer {openai_key}"},
                    timeout=10.0
                )
                if response.status_code == 200:
                    data = response.json()
                    models = []
                    for model in data.get("data", []):
                        model_id = model.get("id", "")
                        # Filter GPT models (gpt-4, gpt-3.5, etc.)
                        if model_id.startswith("gpt-"):
                            display_name = get_gpt_display_name(model_id)
                            max_tokens = get_model_max_tokens(model_id)
                            if display_name:  # Only include known models
                                models.append({
                                    "id": model_id,
                                    "name": display_name,
                                    "max_tokens": max_tokens
                                })
                    # Remove duplicates and sort
                    seen = set()
                    unique_models = []
                    for m in models:
                        if m["id"] not in seen:
                            seen.add(m["id"])
                            unique_models.append(m)
                    unique_models.sort(key=lambda x: x["name"], reverse=True)
                    providers["openai"] = {"models": unique_models}
        except Exception as e:
            print(f"Failed to fetch OpenAI models: {e}")

    # Load config for default values
    try:
        from src.core.llm import load_config
        config = load_config()
        default = config.get("default", {})
    except Exception:
        default = {"provider": "anthropic", "model": "claude-sonnet-4-20250514"}

    return JSONResponse(content={
        "providers": providers,
        "default": default
    })


def get_claude_display_name(model_id: str) -> str:
    """Get display name for Claude model."""
    # Map model IDs to display names
    name_map = {
        "claude-sonnet-4": "Claude Sonnet 4",
        "claude-opus-4": "Claude Opus 4",
        "claude-3-7-sonnet": "Claude 3.7 Sonnet",
        "claude-3-5-sonnet": "Claude 3.5 Sonnet",
        "claude-3-5-haiku": "Claude 3.5 Haiku",
        "claude-3-opus": "Claude 3 Opus",
        "claude-3-sonnet": "Claude 3 Sonnet",
        "claude-3-haiku": "Claude 3 Haiku",
    }
    for prefix, name in name_map.items():
        if model_id.startswith(prefix):
            return name
    # Fallback: format model_id
    return model_id.replace("-", " ").title()


def get_gpt_display_name(model_id: str) -> str:
    """Get display name for GPT model."""
    name_map = {
        "gpt-5": "GPT-5",
        "gpt-4.1": "GPT-4.1",
        "gpt-4o-mini": "GPT-4o Mini",
        "gpt-4o": "GPT-4o",
        "gpt-4-turbo": "GPT-4 Turbo",
        "gpt-4": "GPT-4",
        "gpt-3.5-turbo": "GPT-3.5 Turbo",
    }
    for prefix, name in name_map.items():
        if model_id.startswith(prefix):
            return name
    return None  # Skip unknown models


def get_model_max_tokens(model_id: str) -> int:
    """Get max output tokens for a model."""
    # Claude models
    if "claude-sonnet-4" in model_id or "claude-opus-4" in model_id:
        return 16384
    if "claude-3-7" in model_id or "claude-3-5" in model_id:
        return 8192
    if "claude-3" in model_id:
        return 4096
    # GPT models
    if "gpt-5" in model_id:
        return 32768
    if "gpt-4.1" in model_id:
        return 32768
    if "gpt-4o" in model_id:
        return 16384
    if "gpt-4-turbo" in model_id:
        return 4096
    if "gpt-4" in model_id:
        return 8192
    if "gpt-3.5" in model_id:
        return 4096
    return 4096  # Default


@app.post("/api/start")
async def start_workflow(request: dict, background_tasks: BackgroundTasks):
    """Start a new workflow."""
    global workflow_running

    if workflow_running:
        return JSONResponse(
            content={"error": "Workflow already running"},
            status_code=400
        )

    user_request = request.get("request", "Create a simple game")
    phase = request.get("phase", "mock")
    llm_config = request.get("llm_config")

    # Reset tracker
    tracker.reset()
    tracker.set_request(user_request)

    # Start workflow in background thread
    def run_workflow():
        global workflow_running
        workflow_running = True
        try:
            from dotenv import load_dotenv
            load_dotenv(project_root / ".env")

            from src.core.state import create_initial_state, DevelopmentPhase
            from src.core.graph import GameCreatorGraph
            from src.core.llm import set_runtime_llm_config

            # Set runtime LLM config if provided
            if llm_config:
                set_runtime_llm_config(llm_config)

            phase_map = {
                "mock": DevelopmentPhase.MOCK,
                "generate": DevelopmentPhase.GENERATE,
                "polish": DevelopmentPhase.POLISH,
                "final": DevelopmentPhase.FINAL
            }

            state = create_initial_state(
                user_request=user_request,
                development_phase=phase_map.get(phase, DevelopmentPhase.MOCK),
                llm_config=llm_config
            )

            graph = GameCreatorGraph()
            graph.run(state)

            # Broadcast completion
            tracker.emit("workflow", AgentStatus.COMPLETED, "Workflow completed")

        except Exception as e:
            tracker.emit("workflow", AgentStatus.ERROR, f"Error: {str(e)}")
        finally:
            workflow_running = False

    background_tasks.add_task(lambda: threading.Thread(target=run_workflow, daemon=True).start())

    return JSONResponse(content={"status": "started"})


@app.post("/api/stop")
async def stop_workflow():
    """Stop current workflow (not implemented - requires interrupt support)."""
    return JSONResponse(content={"status": "stop not implemented"})


def run_server(host: str = "0.0.0.0", port: int = 8080):
    """Run the dashboard server."""
    print(f"Starting dashboard at http://localhost:{port}")
    uvicorn.run(app, host=host, port=port, log_level="info")


if __name__ == "__main__":
    run_server()
