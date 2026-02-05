from datetime import datetime,timedelta
from typing import Dict,List,Any

from config_loaders.agent_config import (
    get_generation_type_for_agent,
    get_generation_metrics_categories,
)
from events.event_bus import EventBus
from events.events import MetricsUpdated
from repositories import MetricsRepository,AgentRepository,ProjectRepository


class MetricsCalculator:
    def __init__(self,event_bus:EventBus):
        self._event_bus=event_bus

    def calculate_token_totals(
        self,agents:List[Dict]
    )->tuple[int,int]:
        total_input=sum(a.get("inputTokens",0) for a in agents)
        total_output=sum(a.get("outputTokens",0) for a in agents)
        return total_input,total_output

    def calculate_progress(
        self,agents:List[Dict]
    )->tuple[int,int,int]:
        completed_count=len([a for a in agents if a["status"]=="completed"])
        total_count=len(agents)
        total_progress=sum(a["progress"] for a in agents)
        overall_progress=(
            int(total_progress/total_count) if total_count>0 else 0
        )
        return completed_count,total_count,overall_progress

    def calculate_tokens_by_type(
        self,agents:List[Dict]
    )->Dict[str,Dict[str,int]]:
        tokens_by_type:Dict[str,Dict[str,int]]={}
        for agent in agents:
            gen_type=get_generation_type_for_agent(agent["type"])
            if gen_type not in tokens_by_type:
                tokens_by_type[gen_type]={"input":0,"output":0}
            tokens_by_type[gen_type]["input"]+=agent.get("inputTokens",0)
            tokens_by_type[gen_type]["output"]+=agent.get("outputTokens",0)
        return tokens_by_type

    def estimate_remaining_time(
        self,agents:List[Dict]
    )->float:
        running_agent=next(
            (a for a in agents if a["status"]=="running"),None
        )
        if not running_agent or running_agent["progress"]<=0:
            return 0.0
        elapsed=(
            datetime.now()
            -datetime.fromisoformat(running_agent["startedAt"])
        ).total_seconds()
        rate=running_agent["progress"]/elapsed if elapsed>0 else 1
        if rate<=0:
            return 0.0
        remaining_progress=100-running_agent["progress"]
        remaining_agents=len(
            [a for a in agents if a["status"]=="pending"]
        )
        return (remaining_progress/rate)+(remaining_agents*100/rate)

    def count_active_generations(self,agents:List[Dict])->int:
        return len([a for a in agents if a["status"]=="running"])

    def update_metrics(
        self,
        session,
        project_id:str,
    )->None:
        agent_repo=AgentRepository(session)
        proj_repo=ProjectRepository(session)
        metrics_repo=MetricsRepository(session)
        agents=agent_repo.get_by_project(project_id)
        project=proj_repo.get(project_id)
        if not project:
            return
        total_input,total_output=self.calculate_token_totals(agents)
        completed_count,total_count,overall_progress=self.calculate_progress(
            agents
        )
        tokens_by_type=self.calculate_tokens_by_type(agents)
        estimated_remaining=self.estimate_remaining_time(agents)
        active_generations=self.count_active_generations(agents)
        existing_metrics=metrics_repo.get(project_id)
        generation_counts=(
            existing_metrics.get("generationCounts",{})
            if existing_metrics
            else {}
        )
        metrics_data={
            "projectId":project_id,
            "totalTokensUsed":total_input+total_output,
            "totalInputTokens":total_input,
            "totalOutputTokens":total_output,
            "estimatedTotalTokens":50000,
            "tokensByType":tokens_by_type,
            "generationCounts":generation_counts,
            "elapsedTimeSeconds":int(
                (datetime.now()-project.created_at).total_seconds()
            ),
            "estimatedRemainingSeconds":int(estimated_remaining),
            "estimatedEndTime":(
                datetime.now()+timedelta(seconds=estimated_remaining)
            ).isoformat()
            if estimated_remaining>0
            else None,
            "completedTasks":completed_count,
            "totalTasks":total_count,
            "progressPercent":overall_progress,
            "currentPhase":project.current_phase,
            "phaseName":f"Phase {project.current_phase}",
            "activeGenerations":active_generations,
        }
        metrics_repo.create_or_update(project_id,metrics_data)
        self._event_bus.publish(
            MetricsUpdated(project_id=project_id,metrics=metrics_data)
        )

    def accumulate_generation_counts(
        self,
        session,
        project_id:str,
        gen_counts:Dict[str,Any],
    )->None:
        metrics_repo=MetricsRepository(session)
        existing=metrics_repo.get(project_id)
        generation_counts=(
            existing.get("generationCounts",{}) if existing else {}
        )
        categories=get_generation_metrics_categories()
        for category,values in gen_counts.items():
            if category not in generation_counts:
                cat_config=categories.get(category,{})
                generation_counts[category]={
                    "count":0,
                    "unit":cat_config.get("unit",""),
                    "calls":0,
                }
            entry=generation_counts[category]
            if"calls" not in entry:
                entry["calls"]=0
            entry["count"]=entry.get("count",0)+values.get("count",0)
            entry["calls"]+=values.get("calls",0)
        metrics_repo.create_or_update(
            project_id,{"generationCounts":generation_counts}
        )
