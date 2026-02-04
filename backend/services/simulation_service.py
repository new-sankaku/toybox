import os
import uuid
import threading
import time
import random
from datetime import datetime
from typing import Optional,Dict,List

from models.database import session_scope
from repositories import (
    ProjectRepository,
    AgentRepository,
    CheckpointRepository,
    AssetRepository,
    MetricsRepository,
    AgentLogRepository,
    SystemLogRepository,
)
from repositories.trace import AgentTraceRepository
from config_loader import (
    get_workflow_dependencies,
    get_initial_task,
    get_task_for_progress,
    get_milestones,
    get_generation_type_for_agent,
    get_agent_assets,
    get_agent_checkpoints,
    get_checkpoint_content,
    get_generation_metrics_categories,
    get_agent_generation_metrics,
    get_checkpoint_category_map,
)
from asset_scanner import get_testdata_path
from events.event_bus import EventBus
from events.events import (
    AgentStarted,
    AgentProgress,
    AgentCompleted,
    AgentResumed,
    CheckpointCreated,
    AssetCreated,
    MetricsUpdated,
    SystemLogCreated,
)
from middleware.logger import get_logger


class SimulationService:
    def __init__(self,event_bus:EventBus):
        self._event_bus=event_bus
        self._simulation_running=False
        self._simulation_thread:Optional[threading.Thread]=None
        self._lock=threading.Lock()
        self._logger=get_logger()

    def start_simulation(self)->None:
        if self._simulation_running:
            return
        self._simulation_running=True
        self._simulation_thread=threading.Thread(
            target=self._simulation_loop,daemon=True
        )
        self._simulation_thread.start()
        self._logger.info("Simulation started")

    def stop_simulation(self)->None:
        self._simulation_running=False
        if self._simulation_thread:
            self._simulation_thread.join(timeout=2)
        self._logger.info("Simulation stopped")

    def _simulation_loop(self)->None:
        while self._simulation_running:
            try:
                with self._lock:
                    self._tick_simulation()
            except Exception as e:
                self._logger.error(
                    f"Simulation tick error: {e}",exc_info=True
                )
            time.sleep(1)

    def _tick_simulation(self)->None:
        with session_scope() as session:
            repo=ProjectRepository(session)
            for p in repo.get_all():
                if p.status=="running":
                    self._simulate_project(session,p.id)

    def _can_start_agent(
        self,session,agent_type:str,project_id:str
    )->bool:
        workflow_deps=get_workflow_dependencies()
        dependencies=workflow_deps.get(agent_type,[])
        agent_repo=AgentRepository(session)
        agents=agent_repo.get_by_project(project_id)
        for dep_type in dependencies:
            dep_agent=next(
                (a for a in agents if a["type"]==dep_type),None
            )
            if not dep_agent or dep_agent["status"]!="completed":
                return False
            cp_repo=CheckpointRepository(session)
            pending_cps=[
                c
                for c in cp_repo.get_by_agent(dep_agent["id"])
                if c["status"]=="pending"
            ]
            if pending_cps:
                return False
            asset_repo=AssetRepository(session)
            pending_assets=asset_repo.get_pending_by_agent(dep_agent["id"])
            if pending_assets:
                return False
        return True

    def _get_next_agents_to_start(
        self,session,project_id:str
    )->List[Dict]:
        agent_repo=AgentRepository(session)
        agents=agent_repo.get_by_project(project_id)
        pending=[a for a in agents if a["status"]=="pending"]
        return [
            a
            for a in pending
            if self._can_start_agent(session,a["type"],project_id)
        ]

    def _simulate_project(self,session,project_id:str)->None:
        proj_repo=ProjectRepository(session)
        agent_repo=AgentRepository(session)
        project=proj_repo.get(project_id)
        if not project:
            return
        agents=agent_repo.get_by_project(project_id)
        running_agents=[a for a in agents if a["status"]=="running"]
        if running_agents:
            for agent in running_agents:
                self._simulate_agent(session,agent)
        else:
            ready_agents=self._get_next_agents_to_start(
                session,project_id
            )
            if ready_agents:
                for agent in ready_agents:
                    self._start_agent(session,agent)
            else:
                completed=all(
                    a["status"]=="completed" for a in agents
                )
                if completed:
                    project.status="completed"
                    project.updated_at=datetime.now()
                    self._add_system_log(
                        session,project_id,"info","System","プロジェクト完了！"
                    )
        self._update_project_metrics(session,project_id)

    def _start_agent(self,session,agent_dict:Dict)->None:
        agent_repo=AgentRepository(session)
        agent=agent_repo.get(agent_dict["id"])
        now=datetime.now()
        agent.status="running"
        agent.progress=0
        agent.started_at=now
        agent.current_task=get_initial_task(agent.type)
        session.flush()
        display_name=(
            agent.metadata_.get("displayName",agent.type)
            if agent.metadata_
            else agent.type
        )
        self._add_agent_log(
            session,agent.id,"info",f"{display_name}エージェント起動",0
        )
        self._add_system_log(
            session,
            agent.project_id,
            "info",
            agent.type,
            f"{display_name}開始",
        )
        self._event_bus.publish(
            AgentStarted(
                project_id=agent.project_id,
                agent_id=agent.id,
                agent=agent_repo.to_dict(agent),
            )
        )

    def _simulate_agent(self,session,agent_dict:Dict)->None:
        if agent_dict["status"]=="waiting_approval":
            return
        agent_repo=AgentRepository(session)
        agent=agent_repo.get(agent_dict["id"])
        increment=random.randint(2,5)
        new_progress=min(100,agent.progress+increment)
        token_increment=random.randint(30,80)
        input_increment=int(token_increment*0.3)
        output_increment=token_increment-input_increment
        agent.tokens_used+=token_increment
        agent.input_tokens+=input_increment
        agent.output_tokens+=output_increment
        old_progress=agent.progress
        agent.progress=new_progress
        agent.current_task=get_task_for_progress(agent.type,new_progress)
        session.flush()
        self._check_milestone_logs(session,agent,old_progress,new_progress)
        self._check_checkpoint_creation(
            session,agent,old_progress,new_progress
        )
        self._check_asset_generation(
            session,agent,old_progress,new_progress
        )
        self._check_trace_generation(
            session,agent,old_progress,new_progress
        )
        agent=agent_repo.get(agent_dict["id"])
        if agent.status=="waiting_approval":
            self._event_bus.publish(
                AgentProgress(
                    project_id=agent.project_id,
                    agent_id=agent.id,
                    progress=new_progress,
                    current_task="承認待ち",
                    tokens_used=agent.tokens_used,
                    message=f"承認待ち (進捗: {new_progress}%)",
                )
            )
            return
        self._event_bus.publish(
            AgentProgress(
                project_id=agent.project_id,
                agent_id=agent.id,
                progress=new_progress,
                current_task=agent.current_task,
                tokens_used=agent.tokens_used,
                message=f"進捗: {new_progress}%",
            )
        )
        if new_progress>=100:
            self._complete_agent(session,agent)

    def _complete_agent(self,session,agent)->None:
        now=datetime.now()
        agent.status="completed"
        agent.progress=100
        agent.completed_at=now
        agent.current_task=None
        session.flush()
        display_name=(
            agent.metadata_.get("displayName",agent.type)
            if agent.metadata_
            else agent.type
        )
        self._add_agent_log(
            session,agent.id,"info",f"{display_name}完了",100
        )
        self._add_system_log(
            session,
            agent.project_id,
            "info",
            agent.type,
            f"{display_name}完了",
        )
        agent_repo=AgentRepository(session)
        self._finalize_generation_count(session,agent,agent.project_id)
        self._event_bus.publish(
            AgentCompleted(
                project_id=agent.project_id,
                agent_id=agent.id,
                agent=agent_repo.to_dict(agent),
            )
        )
        self._resume_paused_subsequent_agents(session,agent)

    def _resume_paused_subsequent_agents(
        self,session,completed_agent
    )->None:
        agent_repo=AgentRepository(session)
        syslog_repo=SystemLogRepository(session)
        agents=agent_repo.get_by_project(completed_agent.project_id)
        completed_phase=completed_agent.phase or 0
        for agent_dict in agents:
            if agent_dict["status"]!="paused":
                continue
            agent_phase=agent_dict.get("phase",0)
            if agent_phase<=completed_phase:
                continue
            if not self._can_start_agent(
                session,agent_dict["type"],completed_agent.project_id
            ):
                continue
            agent=agent_repo.get(agent_dict["id"])
            agent.status="running"
            agent.updated_at=datetime.now()
            session.flush()
            display_name=(
                agent.metadata_.get("displayName",agent.type)
                if agent.metadata_
                else agent.type
            )
            syslog_repo.add_log(
                agent.project_id,
                "info",
                "System",
                f"エージェント {display_name} を自動再開",
            )
            self._event_bus.publish(
                AgentResumed(
                    project_id=agent.project_id,
                    agent_id=agent.id,
                    agent=agent_repo.to_dict(agent),
                    reason="previous_agent_completed",
                )
            )

    def _check_milestone_logs(
        self,session,agent,old_progress:int,new_progress:int
    )->None:
        milestones=get_milestones(agent.type)
        for milestone_progress,level,message in milestones:
            if old_progress<milestone_progress<=new_progress:
                self._add_agent_log(
                    session,agent.id,level,message,milestone_progress
                )
                if level in ("warn","error"):
                    self._add_system_log(
                        session,
                        agent.project_id,
                        level,
                        agent.type,
                        message,
                    )

    def _check_checkpoint_creation(
        self,session,agent,old_progress:int,new_progress:int
    )->None:
        checkpoint_points=self._get_checkpoint_points(agent.type)
        for cp_progress,cp_type,cp_title in checkpoint_points:
            if old_progress<cp_progress<=new_progress:
                cp_repo=CheckpointRepository(session)
                existing=[
                    c
                    for c in cp_repo.get_by_agent(agent.id)
                    if c["type"]==cp_type
                ]
                if not existing:
                    self._create_agent_checkpoint(
                        session,agent,cp_type,cp_title
                    )

    def _should_auto_approve(
        self,session,project_id:str,cp_type:str
    )->bool:
        proj_repo=ProjectRepository(session)
        project=proj_repo.get(project_id)
        if not project:
            return False
        rules=(project.config or {}).get("autoApprovalRules",[])
        if not rules:
            return False
        category=get_checkpoint_category_map().get(cp_type,"document")
        for rule in rules:
            if rule.get("category")==category:
                return rule.get("enabled",False)
        return False

    def _create_agent_checkpoint(
        self,session,agent,cp_type:str,title:str
    )->None:
        cp_id=f"cp-{uuid.uuid4().hex[:8]}"
        now=datetime.now()
        content=self._generate_checkpoint_content(agent.type,cp_type)
        auto_approve=self._should_auto_approve(
            session,agent.project_id,cp_type
        )
        category=get_checkpoint_category_map().get(cp_type,"document")
        from models.tables import Checkpoint

        checkpoint=Checkpoint(
            id=cp_id,
            project_id=agent.project_id,
            agent_id=agent.id,
            type=cp_type,
            title=title,
            description=f"{agent.metadata_.get('displayName', agent.type) if agent.metadata_ else agent.type}の成果物を確認してください",
            content_category=category,
            output={
                "type":"document",
                "format":"markdown",
                "content":content,
            },
            status="approved" if auto_approve else"pending",
            resolved_at=now if auto_approve else None,
            created_at=now,
            updated_at=now,
        )
        session.add(checkpoint)
        session.flush()
        if auto_approve:
            self._add_system_log(
                session,
                agent.project_id,
                "info",
                "System",
                f"自動承認: {title}",
            )
        else:
            agent.status="waiting_approval"
            session.flush()
            self._add_system_log(
                session,
                agent.project_id,
                "info",
                "System",
                f"承認作成: {title}",
            )
        cp_repo=CheckpointRepository(session)
        self._event_bus.publish(
            CheckpointCreated(
                project_id=agent.project_id,
                checkpoint_id=cp_id,
                agent_id=agent.id,
                checkpoint=cp_repo.to_dict(checkpoint),
                auto_approved=auto_approve,
            )
        )

    def _check_asset_generation(
        self,session,agent,old_progress:int,new_progress:int
    )->None:
        asset_points=self._get_asset_points(agent.type)
        for point_progress,asset_type,asset_name,asset_size in asset_points:
            if old_progress<point_progress<=new_progress:
                asset_repo=AssetRepository(session)
                existing=[
                    a
                    for a in asset_repo.get_by_project(agent.project_id)
                    if a["name"]==asset_name
                    and a["agent"]
                    ==(
                        agent.metadata_.get("displayName",agent.type)
                        if agent.metadata_
                        else agent.type
                    )
                ]
                if not existing:
                    self._create_asset(
                        session,agent,asset_type,asset_name,asset_size
                    )
                    self._increment_generation_count(
                        session,agent.type,agent.project_id
                    )

    def _check_trace_generation(
        self,session,agent,old_progress:int,new_progress:int
    )->None:
        trace_points=[20,50,80]
        for point in trace_points:
            if old_progress<point<=new_progress:
                self._create_simulation_trace(session,agent,point)

    def _create_simulation_trace(
        self,session,agent,progress:int
    )->None:
        trace_repo=AgentTraceRepository(session)
        display_name=(
            agent.metadata_.get("displayName",agent.type)
            if agent.metadata_
            else agent.type
        )
        input_tokens=random.randint(500,2000)
        output_tokens=random.randint(200,1000)
        sample_prompt=f"""あなたは{display_name}エージェントです。
以下のタスクを実行してください。

## タスク
プロジェクトの{agent.type}フェーズの処理を行います。

## 入力
進捗:{progress}%
"""
        sample_response=f"""## 処理結果

{display_name}の処理が完了しました。

### 実行内容
-データ分析を実施
-結果を生成
-品質チェックを実行

### 出力
処理は正常に完了しました。次のステップに進む準備ができています。
"""
        trace_repo.create_trace(
            project_id=agent.project_id,
            agent_id=agent.id,
            agent_type=agent.type,
            input_context={"progress":progress,"phase":agent.phase},
            model_used="simulation",
        )
        traces=trace_repo.get_by_agent(agent.id)
        if traces:
            latest_trace_id=traces[0]["id"]
            trace_repo.update_prompt(latest_trace_id,sample_prompt)
            trace_repo.complete_trace(
                trace_id=latest_trace_id,
                llm_response=sample_response,
                output_data={"type":"document","progress":progress},
                tokens_input=input_tokens,
                tokens_output=output_tokens,
                status="completed",
            )

    def _should_auto_approve_asset(
        self,session,project_id:str,asset_type:str
    )->bool:
        proj_repo=ProjectRepository(session)
        project=proj_repo.get(project_id)
        if not project:
            return False
        rules=(project.config or {}).get("autoApprovalRules",[])
        if not rules:
            return False
        for rule in rules:
            if rule.get("category")==asset_type:
                return rule.get("enabled",False)
        return False

    def _create_asset(
        self,
        session,
        agent,
        asset_type:str,
        name:str,
        size:str,
    )->None:
        testdata_path=get_testdata_path()
        real_file=self._find_real_file(
            session,testdata_path,asset_type,agent.project_id
        )
        display_name=(
            agent.metadata_.get("displayName",agent.type)
            if agent.metadata_
            else agent.type
        )
        actual_type=real_file["type"] if real_file else asset_type
        auto_approve=self._should_auto_approve_asset(
            session,agent.project_id,actual_type
        )
        approval_status="approved" if auto_approve else"pending"
        from models.tables import Asset

        if real_file:
            asset=Asset(
                id=f"asset-{uuid.uuid4().hex[:8]}",
                project_id=agent.project_id,
                agent_id=agent.id,
                name=real_file["name"],
                type=real_file["type"],
                agent=display_name,
                size=real_file["size"],
                url=real_file["url"],
                thumbnail=real_file["thumbnail"],
                duration=self._random_duration()
                if real_file["type"]=="audio"
                else None,
                approval_status=approval_status,
                created_at=datetime.now(),
            )
            log_msg=f"アセット生成: {real_file['name']}"+(
                " (自動承認)" if auto_approve else""
            )
            self._add_system_log(
                session,agent.project_id,"info",display_name,log_msg
            )
        else:
            url=(
                f"/assets/{name}"
                if asset_type in ("image","audio")
                else None
            )
            thumbnail=(
                f"/thumbnails/{name}" if asset_type=="image" else None
            )
            asset=Asset(
                id=f"asset-{uuid.uuid4().hex[:8]}",
                project_id=agent.project_id,
                agent_id=agent.id,
                name=name,
                type=asset_type,
                agent=display_name,
                size=size,
                url=url,
                thumbnail=thumbnail,
                duration=self._random_duration()
                if asset_type=="audio"
                else None,
                approval_status=approval_status,
                created_at=datetime.now(),
            )
            log_msg=f"アセット生成: {name}"+(
                " (自動承認)" if auto_approve else""
            )
            self._add_system_log(
                session,agent.project_id,"info",display_name,log_msg
            )
        session.add(asset)
        session.flush()
        if not auto_approve:
            agent.status="waiting_approval"
            session.flush()
        asset_repo=AssetRepository(session)
        self._event_bus.publish(
            AssetCreated(
                project_id=agent.project_id,
                asset=asset_repo.to_dict(asset),
                auto_approved=auto_approve,
            )
        )

    def _find_real_file(
        self,
        session,
        testdata_path:str,
        asset_type:str,
        project_id:str,
    )->Optional[Dict]:
        subdir_map={"image":"image","audio":"mp3","video":"movie"}
        subdir=subdir_map.get(asset_type)
        if not subdir:
            return None
        scan_path=os.path.join(testdata_path,subdir)
        if not os.path.exists(scan_path):
            return None
        all_files=[]
        for root,dirs,files in os.walk(scan_path):
            for filename in files:
                file_path=os.path.join(root,filename)
                relative_path=os.path.relpath(file_path,testdata_path)
                all_files.append(
                    {
                        "path":file_path,
                        "name":filename,
                        "relative":relative_path.replace(os.sep,"/"),
                    }
                )
        if not all_files:
            return None
        asset_repo=AssetRepository(session)
        used_files=set(
            a["url"]
            for a in asset_repo.get_by_project(project_id)
            if a.get("url")
        )
        available=[
            f
            for f in all_files
            if f"/testdata/{f['relative']}" not in used_files
        ]
        if not available:
            available=all_files
        chosen=random.choice(available)
        try:
            stat=os.stat(chosen["path"])
            from asset_scanner import format_file_size,get_file_type

            file_type=get_file_type(chosen["name"])
            return {
                "name":chosen["name"],
                "type":file_type,
                "size":format_file_size(stat.st_size),
                "url":f"/testdata/{chosen['relative']}",
                "thumbnail":f"/testdata/{chosen['relative']}"
                if file_type=="image"
                else None,
            }
        except Exception as e:
            self._logger.debug(
                f"Error reading file stat: {chosen['path']}: {e}"
            )
            return None

    def _random_duration(self)->str:
        seconds=random.randint(5,180)
        mins=seconds//60
        secs=seconds%60
        return f"{mins}:{secs:02d}"

    def _get_asset_points(self,agent_type:str)->List[tuple]:
        assets=get_agent_assets(agent_type)
        return [
            (
                a.get("progress",0),
                a.get("type","document"),
                a.get("name",""),
                a.get("size",""),
            )
            for a in assets
        ]

    def _get_checkpoint_points(self,agent_type:str)->List[tuple]:
        checkpoints=get_agent_checkpoints(agent_type)
        return [
            (
                c.get("progress",90),
                c.get("type","review"),
                c.get("title","レビュー"),
            )
            for c in checkpoints
        ]

    def _generate_checkpoint_content(
        self,agent_type:str,cp_type:str
    )->str:
        return get_checkpoint_content(cp_type)

    def _add_agent_log(
        self,
        session,
        agent_id:str,
        level:str,
        message:str,
        progress:int=None,
    )->None:
        repo=AgentLogRepository(session)
        repo.add_log(agent_id,level,message,progress)

    def _add_system_log(
        self,
        session,
        project_id:str,
        level:str,
        source:str,
        message:str,
    )->None:
        repo=SystemLogRepository(session)
        log_dict=repo.add_log(project_id,level,source,message)
        self._event_bus.publish(
            SystemLogCreated(project_id=project_id,log=log_dict)
        )

    def _increment_generation_count(
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
        generation_counts=(
            existing.get("generationCounts",{}) if existing else {}
        )
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
        metrics_repo.create_or_update(
            project_id,{"generationCounts":generation_counts}
        )

    def _finalize_generation_count(
        self,session,agent,project_id:str
    )->None:
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
        generation_counts=(
            existing.get("generationCounts",{}) if existing else {}
        )
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
        metrics_repo.create_or_update(
            project_id,{"generationCounts":generation_counts}
        )

    def _update_project_metrics(self,session,project_id:str)->None:
        from datetime import timedelta

        agent_repo=AgentRepository(session)
        proj_repo=ProjectRepository(session)
        metrics_repo=MetricsRepository(session)
        agents=agent_repo.get_by_project(project_id)
        project=proj_repo.get(project_id)
        if not project:
            return
        total_input=sum(a.get("inputTokens",0) for a in agents)
        total_output=sum(a.get("outputTokens",0) for a in agents)
        completed_count=len(
            [a for a in agents if a["status"]=="completed"]
        )
        total_count=len(agents)
        total_progress=sum(a["progress"] for a in agents)
        overall_progress=(
            int(total_progress/total_count) if total_count>0 else 0
        )
        tokens_by_type={}
        for agent in agents:
            gen_type=get_generation_type_for_agent(agent["type"])
            if gen_type not in tokens_by_type:
                tokens_by_type[gen_type]={"input":0,"output":0}
            tokens_by_type[gen_type]["input"]+=agent.get("inputTokens",0)
            tokens_by_type[gen_type]["output"]+=agent.get("outputTokens",0)
        running_agent=next(
            (a for a in agents if a["status"]=="running"),None
        )
        estimated_remaining=0
        if running_agent and running_agent["progress"]>0:
            elapsed=(
                datetime.now()
                -datetime.fromisoformat(running_agent["startedAt"])
            ).total_seconds()
            rate=running_agent["progress"]/elapsed if elapsed>0 else 1
            remaining_progress=100-running_agent["progress"]
            remaining_agents=len(
                [a for a in agents if a["status"]=="pending"]
            )
            estimated_remaining=(
                (remaining_progress/rate)+(remaining_agents*100/rate)
                if rate>0
                else 0
            )
        active_generations=len(
            [a for a in agents if a["status"]=="running"]
        )
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
