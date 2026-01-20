from testdata import TestDataStore


def register_websocket_handlers(sio,data_store:TestDataStore):

    @sio.event
    def connect(sid,environ):
        print(f"[WebSocket] Client connected: {sid}")
        sio.emit('connection:state_sync',{
            "status":"connected",
            "sid":sid
        },room=sid)

    @sio.event
    def disconnect(sid):
        print(f"[WebSocket] Client disconnected: {sid}")
        data_store.remove_all_subscriptions(sid)

    @sio.event
    def subscribe_project(sid,data):
        project_id = data.get('projectId') if isinstance(data,dict) else data
        print(f"[WebSocket] Client {sid} subscribing to project: {project_id}")

        project = data_store.get_project(project_id)
        if not project:
            sio.emit('error:state',{
                "message":f"Project not found: {project_id}",
                "code":"PROJECT_NOT_FOUND"
            },room=sid)
            return

        data_store.add_subscription(project_id,sid)
        sio.enter_room(sid,f"project:{project_id}")
        agents = data_store.get_agents_by_project(project_id)
        checkpoints = data_store.get_checkpoints_by_project(project_id)
        metrics = data_store.get_project_metrics(project_id)

        sio.emit('connection:state_sync',{
            "project":project,
            "agents":agents,
            "checkpoints":checkpoints,
            "metrics":metrics
        },room=sid)

        print(f"[WebSocket] Sent state sync to {sid} for project {project_id}")

    @sio.event
    def unsubscribe_project(sid,data):
        project_id = data.get('projectId') if isinstance(data,dict) else data
        print(f"[WebSocket] Client {sid} unsubscribing from project: {project_id}")

        data_store.remove_subscription(project_id,sid)
        sio.leave_room(sid,f"project:{project_id}")

    @sio.event
    def checkpoint_resolve(sid,data):
        checkpoint_id = data.get('checkpointId')
        resolution = data.get('resolution')
        feedback = data.get('feedback')

        print(f"[WebSocket] Checkpoint resolution: {checkpoint_id} -> {resolution}")

        if resolution not in ("approved","rejected","revision_requested"):
            sio.emit('error:state',{
                "message":"Invalid resolution",
                "code":"INVALID_RESOLUTION"
            },room=sid)
            return

        checkpoint = data_store.resolve_checkpoint(checkpoint_id,resolution,feedback)

        if not checkpoint:
            sio.emit('error:state',{
                "message":f"Checkpoint not found: {checkpoint_id}",
                "code":"CHECKPOINT_NOT_FOUND"
            },room=sid)
            return

        project_id = checkpoint["projectId"]
        sio.emit('checkpoint:resolved',{
            "checkpointId":checkpoint_id,
            "projectId":project_id,
            "agentId":checkpoint["agentId"],
            "resolution":resolution,
            "feedback":feedback,
            "checkpoint":checkpoint
        },room=f"project:{project_id}")

    @sio.on('subscribe:project')
    def on_subscribe_project(sid,data):
        return subscribe_project(sid,data)

    @sio.on('unsubscribe:project')
    def on_unsubscribe_project(sid,data):
        return unsubscribe_project(sid,data)

    @sio.on('checkpoint:resolve')
    def on_checkpoint_resolve(sid,data):
        return checkpoint_resolve(sid,data)
