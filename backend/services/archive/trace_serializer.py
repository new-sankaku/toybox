from typing import Dict,List

from models.tables import AgentLog,AgentTrace


def serialize_trace(trace:AgentTrace)->Dict:
    return {
        "id":trace.id,
        "projectId":trace.project_id,
        "agentId":trace.agent_id,
        "agentType":trace.agent_type,
        "status":trace.status,
        "inputContext":trace.input_context,
        "promptSent":trace.prompt_sent,
        "llmResponse":trace.llm_response,
        "outputData":trace.output_data,
        "tokensInput":trace.tokens_input,
        "tokensOutput":trace.tokens_output,
        "durationMs":trace.duration_ms,
        "errorMessage":trace.error_message,
        "modelUsed":trace.model_used,
        "startedAt":trace.started_at.isoformat() if trace.started_at else None,
        "completedAt":trace.completed_at.isoformat() if trace.completed_at else None,
    }


def serialize_traces(traces:List[AgentTrace])->List[Dict]:
    return [serialize_trace(t) for t in traces]


def serialize_log(log:AgentLog)->Dict:
    return {
        "id":log.id,
        "agentId":log.agent_id,
        "level":log.level,
        "message":log.message,
        "progress":log.progress,
        "timestamp":log.created_at.isoformat() if log.created_at else None,
    }


def serialize_logs(logs:List[AgentLog])->List[Dict]:
    return [serialize_log(log) for log in logs]
