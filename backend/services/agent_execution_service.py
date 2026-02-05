import asyncio
import threading
from typing import Optional,Dict,Any
from agents.base import AgentType,AgentStatus
from agents.api_runner import ApiAgentRunner,LeaderWorkerOrchestrator
from agents.exceptions import TokenBudgetExceededError
from middleware.logger import get_logger
from services.agent_event_emitter import AgentEventEmitter
from services.agent_execution_context import AgentExecutionContextBuilder


class AgentExecutionService:
    def __init__(
        self,
        project_service,
        agent_service,
        workflow_service,
        intervention_service,
        trace_service,
        event_bus=None,
        sio=None,
    )->None:
        self._project_service=project_service
        self._agent_service=agent_service
        self._workflow_service=workflow_service
        self._trace_service=trace_service
        self._event_bus=event_bus
        self._sio=sio
        self._agent_runner:Optional[ApiAgentRunner]=None
        self._running_agents:Dict[str,bool]={}
        self._lock=threading.Lock()
        self._logger=get_logger()
        self._emitter=AgentEventEmitter(
            agent_service,
            workflow_service,
            intervention_service,
            event_bus,
            sio,
        )
        self._context_builder=AgentExecutionContextBuilder(
            project_service,
            agent_service,
            trace_service,
        )
        self._register_service_skills()

    def _register_service_skills(self)->None:
        try:
            from skills.registry import get_skill_registry,register_service_skills
            registry=get_skill_registry()
            register_service_skills(
                registry,
                self._agent_service,
                self._trace_service,
                self,
                self._event_bus,
            )
            self._logger.info("Service-dependent skills registered")
        except Exception as e:
            self._logger.warning(f"Failed to register service skills: {e}")

    def set_agent_runner(self,runner:ApiAgentRunner)->None:
        self._agent_runner=runner
        if runner:
            runner.set_services(self._trace_service,self._agent_service)
            runner.set_status_callback(self._on_agent_status_change)

    def _on_agent_status_change(self,agent_id:str,status:AgentStatus)->None:
        status_map={
            AgentStatus.PENDING:"pending",
            AgentStatus.RUNNING:"running",
            AgentStatus.WAITING_APPROVAL:"waiting_approval",
            AgentStatus.WAITING_RESPONSE:"waiting_response",
            AgentStatus.WAITING_PROVIDER:"waiting_provider",
            AgentStatus.PAUSED:"paused",
            AgentStatus.COMPLETED:"completed",
            AgentStatus.FAILED:"failed",
        }
        self._agent_service.update_agent(
            agent_id,
            {"status":status_map.get(status,"running")},
        )

    async def execute_agent(
        self,
        project_id:str,
        agent_id:str,
    )->Dict[str,Any]:
        if not self._agent_runner:
            self._logger.warning(f"Agent runner not configured: agent_id={agent_id}")
            return {"success":False,"error":"Agent runner not configured"}
        agent=self._context_builder.validate_agent(agent_id)
        if not agent:
            return {"success":False,"error":"Agent not found"}
        project=self._context_builder.validate_project(project_id)
        if not project:
            return {"success":False,"error":"Project not found"}
        if not self._context_builder.can_start_agent(project_id,agent["type"]):
            self._logger.info(f"Dependencies not met: agent_type={agent['type']}")
            return {"success":False,"error":"Dependencies not met"}
        try:
            AgentType(agent["type"])
        except ValueError:
            return {"success":False,"error":f"Unknown agent type: {agent['type']}"}
        self._context_builder.mark_agent_running(agent_id)
        self._emitter.emit_started(agent_id,project_id)
        self._emitter.emit_pool_speech(agent_id,project_id,"started")
        callbacks=self._emitter.create_callbacks(agent_id,project_id)
        context=self._context_builder.build_context(project,agent,callbacks)
        with self._lock:
            self._running_agents[agent_id]=True
        try:
            await self._wait_for_provider(project,agent_id,agent["type"],project_id)
            output=await self._agent_runner.run_agent(context)
            return self._handle_execution_result(output,agent_id,project_id)
        except TokenBudgetExceededError as e:
            self._logger.warning(
                f"Token budget exceeded: agent_id={agent_id} used={e.used} limit={e.limit}"
            )
            self._context_builder.mark_agent_failed(agent_id,str(e))
            self._emitter.emit_failed(agent_id,project_id,str(e))
            return {"success":False,"error":str(e)}
        except Exception as e:
            self._logger.error(
                f"execute_agent failed: agent_id={agent_id} error={e}",
                exc_info=True,
            )
            self._context_builder.mark_agent_failed(agent_id,str(e))
            self._emitter.emit_failed(agent_id,project_id,str(e))
            return {"success":False,"error":str(e)}
        finally:
            with self._lock:
                self._running_agents.pop(agent_id,None)

    def _handle_execution_result(
        self,
        output,
        agent_id:str,
        project_id:str,
    )->Dict[str,Any]:
        if output.status==AgentStatus.COMPLETED:
            if output.generation_counts:
                self._project_service.accumulate_generation_counts(
                    project_id,
                    output.generation_counts,
                )
            self._context_builder.mark_agent_completed(agent_id,output.tokens_used)
            self._project_service.refresh_project_metrics(project_id)
            self._emitter.emit_completed(agent_id,project_id)
            started_agents=self._agent_service.start_next_agents(project_id)
            if started_agents:
                self._logger.info(
                    f"Started {len(started_agents)} next agents after {agent_id}"
                )
            return {"success":True,"output":output.output}
        self._context_builder.mark_agent_failed(agent_id,output.error)
        self._emitter.emit_failed(agent_id,project_id,output.error or"")
        return {"success":False,"error":output.error}

    async def _wait_for_provider(
        self,
        project:Dict,
        agent_id:str,
        agent_type:str,
        project_id:str,
    )->None:
        provider_id=self._context_builder.get_provider_id(project,agent_type)
        if not provider_id:
            return

        def on_waiting(attempt:int)->None:
            self._agent_service.update_agent(agent_id,{
                "status":"waiting_provider",
                "currentTask":f"API接続待機中 ({provider_id}, 確認{attempt}回目)",
            })
            self._emitter.emit_waiting_provider(
                agent_id,project_id,provider_id,attempt
            )
            self._emitter.emit_pool_speech(agent_id,project_id,"waiting_provider")

        def on_recovered(attempt:int)->None:
            self._agent_service.update_agent(agent_id,{
                "status":"running",
                "currentTask":"API接続回復、処理再開",
            })
            self._emitter.emit_progress(
                agent_id,project_id,0,"",
                f"API接続回復 ({attempt}回の確認後)"
            )

        await self._context_builder.wait_for_provider_if_needed(
            project,agent_id,agent_type,on_waiting,on_recovered
        )

    async def execute_leader_with_workers(
        self,
        project_id:str,
        leader_agent_id:str,
    )->Dict[str,Any]:
        if not self._agent_runner:
            return {"success":False,"error":"Agent runner not configured"}
        agent=self._context_builder.validate_agent(leader_agent_id)
        if not agent:
            return {"success":False,"error":"Leader agent not found"}
        project=self._context_builder.validate_project(project_id)
        if not project:
            return {"success":False,"error":"Project not found"}
        try:
            AgentType(agent["type"])
        except ValueError:
            return {"success":False,"error":f"Unknown agent type: {agent['type']}"}
        quality_settings=self._workflow_service.get_quality_settings(project_id)
        quality_dict={
            k:{"enabled":v.enabled,"maxRetries":v.max_retries}
            for k,v in quality_settings.items()
        }
        orchestrator=LeaderWorkerOrchestrator(
            agent_runner=self._agent_runner,
            quality_settings=quality_dict,
            on_progress=lambda t,p,m:self._emitter.emit_progress(
                leader_agent_id,project_id,p,m
            ),
            on_checkpoint=lambda t,d:self._emitter.emit_checkpoint(
                leader_agent_id,project_id,t,d
            ),
            on_worker_created=lambda w,t:self._emitter.emit_worker_created(
                project_id,leader_agent_id,w,t
            ),
            on_worker_status=lambda w,s,d:self._emitter.emit_worker_status(
                project_id,w,s,d
            ),
            on_worker_speech=lambda wid,msg:self._emitter.emit_speech(
                wid,project_id,msg,"llm"
            ),
        )
        self._context_builder.mark_agent_running(leader_agent_id,"Leader実行開始")
        self._emitter.emit_started(leader_agent_id,project_id)
        callbacks=self._emitter.create_callbacks(leader_agent_id,project_id)
        context=self._context_builder.build_context(project,agent,callbacks)
        with self._lock:
            self._running_agents[leader_agent_id]=True
        try:
            await self._wait_for_provider(
                project,leader_agent_id,agent["type"],project_id
            )
            results=await orchestrator.run_leader_with_workers(context)
            if results.get("human_review_required"):
                self._context_builder.mark_agent_waiting_approval(leader_agent_id)
            else:
                self._context_builder.mark_agent_completed(leader_agent_id)
                self._emitter.emit_completed(leader_agent_id,project_id)
            return {"success":True,"results":results}
        except Exception as e:
            self._logger.error(
                f"execute_leader_with_workers failed: leader_id={leader_agent_id} error={e}",
                exc_info=True,
            )
            self._context_builder.mark_agent_failed(leader_agent_id,str(e))
            self._emitter.emit_failed(leader_agent_id,project_id,str(e))
            return {"success":False,"error":str(e)}
        finally:
            with self._lock:
                self._running_agents.pop(leader_agent_id,None)

    def get_running_agents(self)->Dict[str,bool]:
        with self._lock:
            return dict(self._running_agents)

    def cancel_agent(self,agent_id:str)->bool:
        with self._lock:
            if agent_id not in self._running_agents:
                return False
            self._running_agents.pop(agent_id,None)
            self._context_builder.mark_agent_failed(agent_id,"キャンセルされました")
            agent=self._agent_service.get_agent(agent_id)
            if agent:
                project_id=agent.get("projectId","")
                self._emitter.emit_failed(
                    agent_id,project_id,"キャンセルされました"
                )
            return True

    def re_execute_agent(self,project_id:str,agent_id:str)->None:
        def _run()->None:
            loop=asyncio.new_event_loop()
            asyncio.set_event_loop(loop)
            try:
                agent=self._agent_service.get_agent(agent_id)
                if not agent:
                    self._logger.warning(f"re_execute_agent: agent not found: {agent_id}")
                    return
                self._logger.info(
                    f"re_execute_agent: starting agent_id={agent_id} "
                    f"type={agent.get('type', '')}"
                )
                if agent.get("type","").endswith("_leader"):
                    loop.run_until_complete(
                        self.execute_leader_with_workers(project_id,agent_id)
                    )
                else:
                    loop.run_until_complete(self.execute_agent(project_id,agent_id))
            except Exception as e:
                self._logger.error(
                    f"re_execute_agent failed: agent_id={agent_id} error={e}",
                    exc_info=True,
                )
            finally:
                loop.close()
        thread=threading.Thread(target=_run,daemon=True)
        thread.start()
