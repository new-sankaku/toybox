"""
Dashboard Server - FastAPI + WebSocket for real-time agent monitoring.
"""

import sys
import asyncio
import threading
import json
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
    html_path = static_dir / "index.html"
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
    """Get LLM configuration (providers and models)."""
    try:
        from src.core.llm import load_config
        config = load_config()
        providers = config.get("providers", {})
        default = config.get("default", {})
        return JSONResponse(content={
            "providers": providers,
            "default": default
        })
    except Exception as e:
        return JSONResponse(
            content={"error": str(e)},
            status_code=500
        )


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
