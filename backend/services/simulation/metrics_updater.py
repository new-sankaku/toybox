"""
Metrics Updater Module

シミュレーション用メトリクス更新を担当
"""

import random
from datetime import datetime,timedelta

from repositories import AgentRepository,ProjectRepository,MetricsRepository
from config_loaders.agent_config import (
    get_generation_type_for_agent,
    get_agent_assets,
    get_agent_generation_metrics,
    get_generation_metrics_categories,
)
from events.event_bus import EventBus
from events.events import MetricsUpdated


class MetricsUpdater:
    def __init__(self,event_bus:EventBus):
        self._event_bus=event_bus

    def update_project_metrics(self,session,project_id:str)->None:
        agent_repo=AgentRepository(session)
        proj_repo=ProjectRepository(session)
        metrics_repo=MetricsRepository(session)
        agents=agent_repo.get_by_project(project_id)
        project=proj_repo.get(project_id)
        if not project:
            return
        total_input=sum(a.get("inputTokens",0) for a in agents)
        total_output=sum(a.get("outputTokens",0) for a in agents)
        completed_count=len([a for a in agents if a["status"]=="completed"])
        total_count=len(agents)
        total_progress=sum(a["progress"] for a in agents)
        overall_progress=int(total_progress/total_count) if total_count>0 else 0
        tokens_by_type={}
        for agent in agents:
            gen_type=get_generation_type_for_agent(agent["type"])
            if gen_type not in tokens_by_type:
                tokens_by_type[gen_type]={"input":0,"output":0}
            tokens_by_type[gen_type]["input"]+=agent.get("inputTokens",0)
            tokens_by_type[gen_type]["output"]+=agent.get("outputTokens",0)
        running_agent=next((a for a in agents if a["status"]=="running"),None)
        estimated_remaining=0
        if running_agent and running_agent["progress"]>0:
            elapsed=(
                datetime.now()-datetime.fromisoformat(running_agent["startedAt"])
            ).total_seconds()
            rate=running_agent["progress"]/elapsed if elapsed>0 else 1
            remaining_progress=100-running_agent["progress"]
            remaining_agents=len([a for a in agents if a["status"]=="pending"])
            estimated_remaining=(
                (remaining_progress/rate)+(remaining_agents*100/rate)
                if rate>0
                else 0
            )
        active_generations=len([a for a in agents if a["status"]=="running"])
        existing_metrics=metrics_repo.get(project_id)
        generation_counts=(
            existing_metrics.get("generationCounts",{}) if existing_metrics else {}
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

    def increment_generation_count(
        self,session,agent_type:str,project_id:str
    )->None:
        metrics=get_agent_generation_metrics(agent_type)
        if not metrics:
            return
        category=metrics.get("category")
        if not category:
            return
        metrics_repo=MetricsRepository(session)
        existing=metrics_repo.get(project_id)
        generation_counts=existing.get("generationCounts",{}) if existing else {}
        categories=get_generation_metrics_categories()
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
        entry["count"]=entry.get("count",0)+1
        entry["calls"]+=1
        metrics_repo.create_or_update(project_id,{"generationCounts":generation_counts})

    def finalize_generation_count(self,session,agent,project_id:str)->None:
        agent_type=agent.type
        agent_assets=get_agent_assets(agent_type)
        if agent_assets:
            return
        metrics=get_agent_generation_metrics(agent_type)
        if not metrics:
            return
        category=metrics.get("category")
        if not category:
            return
        count_range=metrics.get("count_range",[1,3])
        calls_range=metrics.get("calls_range",[1,3])
        count_val=random.randint(count_range[0],count_range[1])
        calls_val=random.randint(calls_range[0],calls_range[1])
        metrics_repo=MetricsRepository(session)
        existing=metrics_repo.get(project_id)
        generation_counts=existing.get("generationCounts",{}) if existing else {}
        categories=get_generation_metrics_categories()
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
        entry["count"]=entry.get("count",0)+count_val
        entry["calls"]+=calls_val
        metrics_repo.create_or_update(project_id,{"generationCounts":generation_counts})
