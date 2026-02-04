from middleware.logger import get_logger
from services.project_service import ProjectService
from services.agent_service import AgentService
from services.workflow_service import WorkflowService
from services.intervention_service import InterventionService
from services.subscription_manager import SubscriptionManager


def broadcast_navigator_message(sio,project_id:str,speaker:str,text:str,priority:str="normal"):
    """
    Send a navigator message to all clients subscribed to a project.

    Args:
        sio:Socket.IO server instance
        project_id:Target project ID (or"global" for all clients)
        speaker:Speaker name (e.g.,"オペレーター","システム")
        text:Message text
        priority:Message priority ("low","normal","high","critical")
    """
    message_data={
        "speaker":speaker,
        "text":text,
        "priority":priority,
        "source":"server"
    }

    if project_id=="global":
        sio.emit('navigator:message',message_data)
    else:
        sio.emit('navigator:message',message_data,room=f"project:{project_id}")

    get_logger().info(f"Navigator message sent to {project_id}: {text[:50]}...")


def register_websocket_handlers(sio,project_service:ProjectService,agent_service:AgentService,workflow_service:WorkflowService,intervention_service:InterventionService,subscription_manager:SubscriptionManager):

    @sio.event
    def connect(sid,environ):
        get_logger().info(f"WebSocket client connected: {sid}")
        sio.emit('connection:state_sync',{
            "status":"connected",
            "sid":sid
        },room=sid)

    @sio.event
    def disconnect(sid):
        get_logger().info(f"WebSocket client disconnected: {sid}")
        subscription_manager.remove_all_subscriptions(sid)

    @sio.on('subscribe:project')
    def subscribe_project(sid,data):
        project_id=data.get('projectId') if isinstance(data,dict) else data
        get_logger().debug(f"WebSocket client {sid} subscribing to project: {project_id}")

        project=project_service.get_project(project_id)
        if not project:
            sio.emit('error:state',{
                "message":f"Project not found: {project_id}",
                "code":"PROJECT_NOT_FOUND"
            },room=sid)
            return

        subscription_manager.add_subscription(project_id,sid)
        sio.enter_room(sid,f"project:{project_id}")
        agents=agent_service.get_agents_by_project(project_id)
        checkpoints=workflow_service.get_checkpoints_by_project(project_id)
        interventions=intervention_service.get_interventions_by_project(project_id)
        metrics=project_service.get_project_metrics(project_id)
        logs=project_service.get_system_logs(project_id)

        sio.emit('connection:state_sync',{
            "project":project,
            "agents":agents,
            "checkpoints":checkpoints,
            "interventions":interventions,
            "metrics":metrics,
            "logs":logs
        },room=sid)

        get_logger().debug(f"WebSocket sent state sync to {sid} for project {project_id}")

    @sio.on('unsubscribe:project')
    def unsubscribe_project(sid,data):
        project_id=data.get('projectId') if isinstance(data,dict) else data
        get_logger().debug(f"WebSocket client {sid} unsubscribing from project: {project_id}")

        subscription_manager.remove_subscription(project_id,sid)
        sio.leave_room(sid,f"project:{project_id}")

    @sio.on('checkpoint:resolve')
    def checkpoint_resolve(sid,data):
        checkpoint_id=data.get('checkpointId')
        resolution=data.get('resolution')
        feedback=data.get('feedback')

        get_logger().info(f"WebSocket checkpoint resolution: {checkpoint_id} -> {resolution}")

        if resolution not in ("approved","rejected","revision_requested"):
            sio.emit('error:state',{
                "message":"Invalid resolution",
                "code":"INVALID_RESOLUTION"
            },room=sid)
            return

        checkpoint=workflow_service.resolve_checkpoint(checkpoint_id,resolution,feedback)

        if not checkpoint:
            sio.emit('error:state',{
                "message":f"Checkpoint not found: {checkpoint_id}",
                "code":"CHECKPOINT_NOT_FOUND"
            },room=sid)
            return

