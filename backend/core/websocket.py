import socketio
from typing import Dict, Set, Any
from middleware.logger import get_logger


class SocketManager:
    def __init__(self):
        self.sio = socketio.AsyncServer(
            async_mode="asgi", cors_allowed_origins="*", logger=False, engineio_logger=False
        )
        self.subscriptions: Dict[str, Set[str]] = {}

    def get_app(self):
        return socketio.ASGIApp(self.sio)

    async def emit(self, event: str, data: Any, room: str = None):
        try:
            if room:
                await self.sio.emit(event, data, room=room)
            else:
                await self.sio.emit(event, data)
        except Exception as e:
            get_logger().warning(f"Error emitting {event}: {e}")

    async def emit_to_project(self, event: str, data: Any, project_id: str):
        await self.emit(event, data, room=f"project:{project_id}")

    def add_subscription(self, project_id: str, sid: str):
        if project_id not in self.subscriptions:
            self.subscriptions[project_id] = set()
        self.subscriptions[project_id].add(sid)

    def remove_subscription(self, project_id: str, sid: str):
        if project_id in self.subscriptions:
            self.subscriptions[project_id].discard(sid)

    def remove_all_subscriptions(self, sid: str):
        for project_id in self.subscriptions:
            self.subscriptions[project_id].discard(sid)

    def get_subscribers(self, project_id: str) -> Set[str]:
        return self.subscriptions.get(project_id, set()).copy()

    def register_handlers(self):
        @self.sio.event
        async def connect(sid, environ):
            get_logger().info(f"Client connected: {sid}")

        @self.sio.event
        async def disconnect(sid):
            self.remove_all_subscriptions(sid)
            get_logger().info(f"Client disconnected: {sid}")

        @self.sio.on("subscribe:project")
        async def subscribe_project(sid, data):
            project_id = data.get("projectId") if isinstance(data, dict) else data
            if project_id:
                self.sio.enter_room(sid, f"project:{project_id}")
                self.add_subscription(project_id, sid)
                get_logger().debug(f"Client {sid} subscribed to project {project_id}")

        @self.sio.on("unsubscribe:project")
        async def unsubscribe_project(sid, data):
            project_id = data.get("projectId") if isinstance(data, dict) else data
            if project_id:
                self.sio.leave_room(sid, f"project:{project_id}")
                self.remove_subscription(project_id, sid)
