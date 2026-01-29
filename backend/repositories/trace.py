from typing import List, Dict, Any, Optional
from datetime import datetime
from uuid import uuid4
from sqlalchemy.orm import Session
from sqlalchemy import desc
from models.tables import AgentTrace
from .base import BaseRepository


class AgentTraceRepository(BaseRepository[AgentTrace]):
    def __init__(self, session: Session):
        super().__init__(session, AgentTrace)

    def to_dict(self, t: AgentTrace) -> Dict[str, Any]:
        return {
            "id": t.id,
            "projectId": t.project_id,
            "agentId": t.agent_id,
            "agentType": t.agent_type,
            "status": t.status,
            "inputContext": t.input_context,
            "promptSent": t.prompt_sent,
            "llmResponse": t.llm_response,
            "outputSummary": t.output_summary,
            "outputData": t.output_data,
            "tokensInput": t.tokens_input,
            "tokensOutput": t.tokens_output,
            "durationMs": t.duration_ms,
            "errorMessage": t.error_message,
            "modelUsed": t.model_used,
            "startedAt": t.started_at.isoformat() if t.started_at else None,
            "completedAt": t.completed_at.isoformat() if t.completed_at else None,
        }

    def get_by_project(self, project_id: str, limit: int = 100) -> List[Dict]:
        traces = (
            self.session.query(AgentTrace)
            .filter(AgentTrace.project_id == project_id)
            .order_by(desc(AgentTrace.started_at))
            .limit(limit)
            .all()
        )
        return [self.to_dict(t) for t in traces]

    def get_by_agent(self, agent_id: str) -> List[Dict]:
        traces = (
            self.session.query(AgentTrace)
            .filter(AgentTrace.agent_id == agent_id)
            .order_by(desc(AgentTrace.started_at))
            .all()
        )
        return [self.to_dict(t) for t in traces]

    def create_trace(
        self,
        project_id: str,
        agent_id: str,
        agent_type: str,
        input_context: Optional[Dict] = None,
        model_used: Optional[str] = None,
    ) -> Dict:
        trace = AgentTrace(
            id=f"trace-{uuid4().hex[:12]}",
            project_id=project_id,
            agent_id=agent_id,
            agent_type=agent_type,
            status="running",
            input_context=input_context or {},
            model_used=model_used,
            started_at=datetime.now(),
        )
        self.create(trace)
        return self.to_dict(trace)

    def update_prompt(self, trace_id: str, prompt: str) -> Optional[Dict]:
        trace = self.get(trace_id)
        if trace:
            trace.prompt_sent = prompt
            self.update(trace)
            return self.to_dict(trace)
        return None

    def complete_trace(
        self,
        trace_id: str,
        llm_response: str,
        output_data: Optional[Dict] = None,
        tokens_input: int = 0,
        tokens_output: int = 0,
        status: str = "completed",
        output_summary: Optional[str] = None,
    ) -> Optional[Dict]:
        trace = self.get(trace_id)
        if trace:
            trace.llm_response = llm_response
            trace.output_data = output_data or {}
            trace.tokens_input = tokens_input
            trace.tokens_output = tokens_output
            trace.status = status
            if output_summary:
                trace.output_summary = output_summary
            trace.completed_at = datetime.now()
            if trace.started_at:
                trace.duration_ms = int((trace.completed_at - trace.started_at).total_seconds() * 1000)
            self.update(trace)
            return self.to_dict(trace)
        return None

    def fail_trace(self, trace_id: str, error_message: str) -> Optional[Dict]:
        trace = self.get(trace_id)
        if trace:
            trace.status = "error"
            trace.error_message = error_message
            trace.completed_at = datetime.now()
            if trace.started_at:
                trace.duration_ms = int((trace.completed_at - trace.started_at).total_seconds() * 1000)
            self.update(trace)
            return self.to_dict(trace)
        return None

    def delete_by_project(self, project_id: str) -> int:
        count = self.session.query(AgentTrace).filter(AgentTrace.project_id == project_id).delete()
        self.session.flush()
        return count
