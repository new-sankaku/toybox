import uuid
import threading
import time
from datetime import datetime,timedelta
from typing import Optional,Dict,List,Any
import random

from asset_scanner import scan_all_testdata,get_testdata_path
from agent_settings import get_default_quality_settings,QualityCheckConfig


class TestDataStore:
    def __init__(self):
        self.projects:Dict[str,Dict] = {}
        self.agents:Dict[str,Dict] = {}
        self.checkpoints:Dict[str,Dict] = {}
        self.agent_logs:Dict[str,List[Dict]] = {}
        self.system_logs:Dict[str,List[Dict]] = {}
        self.metrics:Dict[str,Dict] = {}
        self.assets:Dict[str,List[Dict]] = {}
        self.subscriptions:Dict[str,set] = {}
        self.quality_settings:Dict[str,Dict[str,QualityCheckConfig]] = {}
        self.interventions:Dict[str,Dict] = {}
        self.uploaded_files:Dict[str,Dict] = {}


        self._simulation_running = False
        self._simulation_thread:Optional[threading.Thread] = None
        self._lock = threading.Lock()


        self._sio = None

        self._init_sample_data()

    def set_sio(self,sio):
        self._sio = sio

    def _emit_event(self,event:str,data:Dict,project_id:str):
        if self._sio:
            try:
                self._sio.emit(event,data,room=f"project:{project_id}")
            except Exception as e:
                print(f"[TestDataStore] Error emitting {event}: {e}")

    def _init_sample_data(self):
        proj_id = "proj-001"
        now = datetime.now()

        self.projects[proj_id] = {
            "id":proj_id,
            "name":"パズルアクションゲーム",
            "description":"物理演算を使ったパズルゲーム。ボールを転がして障害物を避けながらゴールを目指す。",
            "concept":{
                "description":"ボールを転がしてゴールを目指すパズル。重力や摩擦をリアルに再現。",
                "platform":"web",
                "scope":"mvp",
                "genre":"Puzzle",
                "targetAudience":"全年齢"
            },
            "status":"draft",
            "currentPhase":1,
            "state":{},
            "config":{
                "maxTokensPerAgent":100000,
                "enableAutoApproval":False,
                "llmProvider":"mock"
            },
            "createdAt":now.isoformat(),
            "updatedAt":now.isoformat()
        }












        agents_data = [

            {"type":"concept","name":"コンセプト","phase":0},

            {"type":"task_split_1","name":"タスク分割1","phase":1},

            {"type":"concept_detail","name":"コンセプト詳細","phase":2},
            {"type":"scenario","name":"シナリオ","phase":2},
            {"type":"world","name":"世界観","phase":2},
            {"type":"game_design","name":"ゲームデザイン","phase":2},
            {"type":"tech_spec","name":"技術仕様","phase":2},

            {"type":"task_split_2","name":"タスク分割2","phase":3},

            {"type":"asset_character","name":"キャラ","phase":4},
            {"type":"asset_background","name":"背景","phase":4},
            {"type":"asset_ui","name":"UI","phase":4},
            {"type":"asset_effect","name":"エフェクト","phase":4},
            {"type":"asset_bgm","name":"BGM","phase":4},
            {"type":"asset_voice","name":"ボイス","phase":4},
            {"type":"asset_sfx","name":"効果音","phase":4},

            {"type":"task_split_3","name":"タスク分割3","phase":5},

            {"type":"code","name":"コード","phase":6},
            {"type":"event","name":"イベント","phase":6},
            {"type":"ui_integration","name":"UI統合","phase":6},
            {"type":"asset_integration","name":"アセット統合","phase":6},

            {"type":"task_split_4","name":"タスク分割4","phase":7},

            {"type":"unit_test","name":"単体テスト","phase":8},
            {"type":"integration_test","name":"統合テスト","phase":8},
        ]

        for data in agents_data:
            agent_id = f"agent-{proj_id}-{data['type']}"
            self.agents[agent_id] = {
                "id":agent_id,
                "projectId":proj_id,
                "type":data["type"],
                "phase":data["phase"],
                "status":"pending",
                "progress":0,
                "currentTask":None,
                "tokensUsed":0,
                "inputTokens":0,
                "outputTokens":0,
                "startedAt":None,
                "completedAt":None,
                "error":None,
                "parentAgentId":None,
                "metadata":{"displayName":data["name"]},
                "createdAt":now.isoformat()
            }
            self.agent_logs[agent_id] = []


        self.system_logs[proj_id] = []


        testdata_path = get_testdata_path()
        real_assets = scan_all_testdata(testdata_path)
        self.assets[proj_id] = real_assets
        print(f"[TestDataStore] Loaded {len(real_assets)} real assets")

        self.metrics[proj_id] = {
            "projectId":proj_id,
            "totalTokensUsed":0,
            "totalInputTokens":0,
            "totalOutputTokens":0,
            "estimatedTotalTokens":50000,
            "tokensByType":{},
            "elapsedTimeSeconds":0,
            "estimatedRemainingSeconds":0,
            "estimatedEndTime":None,
            "completedTasks":0,
            "totalTasks":6,
            "progressPercent":0,
            "currentPhase":1,
            "phaseName":"Phase 1: 企画・設計",
            "activeGenerations":0
        }

    def start_simulation(self):
        if self._simulation_running:
            return

        self._simulation_running = True
        self._simulation_thread = threading.Thread(target=self._simulation_loop,daemon=True)
        self._simulation_thread.start()
        print("[Simulation] Started")

    def stop_simulation(self):
        self._simulation_running = False
        if self._simulation_thread:
            self._simulation_thread.join(timeout=2)
        print("[Simulation] Stopped")

    def _simulation_loop(self):
        while self._simulation_running:
            try:
                with self._lock:
                    self._tick_simulation()
            except Exception as e:
                print(f"[Simulation] Error: {e}")
            time.sleep(1)

    def _tick_simulation(self):
        for project_id,project in list(self.projects.items()):
            if project["status"] == "running":
                self._simulate_project(project_id)

    WORKFLOW_DEPENDENCIES = {
        "concept":[],
        "task_split_1":["concept"],
        "concept_detail":["task_split_1"],
        "scenario":["task_split_1"],
        "world":["task_split_1"],
        "game_design":["task_split_1"],
        "tech_spec":["task_split_1"],
        "task_split_2":["concept_detail","scenario","world","game_design","tech_spec"],
        "asset_character":["task_split_2"],
        "asset_background":["task_split_2"],
        "asset_ui":["task_split_2"],
        "asset_effect":["task_split_2"],
        "asset_bgm":["task_split_2"],
        "asset_voice":["task_split_2"],
        "asset_sfx":["task_split_2"],
        "task_split_3":["asset_character","asset_background","asset_ui","asset_effect","asset_bgm","asset_voice","asset_sfx"],
        "code":["task_split_3"],
        "event":["task_split_3"],
        "ui_integration":["task_split_3"],
        "asset_integration":["task_split_3"],
        "task_split_4":["code","event","ui_integration","asset_integration"],
        "unit_test":["task_split_4"],
        "integration_test":["task_split_4"],
    }

    def _can_start_agent(self,agent_type:str,agents:List[Dict])->bool:
        dependencies = self.WORKFLOW_DEPENDENCIES.get(agent_type,[])
        for dep_type in dependencies:
            dep_agent = next((a for a in agents if a["type"] == dep_type),None)
            if not dep_agent or dep_agent["status"] != "completed":
                return False
        return True

    def _get_next_agents_to_start(self,agents:List[Dict])->List[Dict]:
        pending = [a for a in agents if a["status"] == "pending"]
        return [a for a in pending if self._can_start_agent(a["type"],agents)]

    def _simulate_project(self,project_id:str):
        project = self.projects.get(project_id)
        if not project:
            return

        agents = [a for a in self.agents.values() if a["projectId"] == project_id]
        running_agents = [a for a in agents if a["status"] == "running"]

        if running_agents:

            for agent in running_agents:
                self._simulate_agent(agent)
        else:

            ready_agents = self._get_next_agents_to_start(agents)
            if ready_agents:

                for agent in ready_agents:
                    self._start_agent(agent)
            else:

                completed = all(a["status"] == "completed" for a in agents)
                if completed:
                    project["status"] = "completed"
                    project["updatedAt"] = datetime.now().isoformat()
                    self._add_system_log(project_id,"info","System","プロジェクト完了！")


        self._update_project_metrics(project_id)

    def _start_agent(self,agent:Dict):
        now = datetime.now()
        agent["status"] = "running"
        agent["progress"] = 0
        agent["startedAt"] = now.isoformat()
        agent["currentTask"] = self._get_initial_task(agent["type"])


        display_name = agent["metadata"].get("displayName",agent["type"])
        self._add_agent_log(agent["id"],"info",f"{display_name}エージェント起動",0)
        self._add_system_log(agent["projectId"],"info",agent["type"],f"{display_name}開始")


        self._emit_event("agent:started",{
            "agentId":agent["id"],
            "projectId":agent["projectId"],
            "agent":agent
        },agent["projectId"])

    def _simulate_agent(self,agent:Dict):
        increment = random.randint(2,5)
        new_progress = min(100,agent["progress"] + increment)
        token_increment = random.randint(30,80)
        input_increment = int(token_increment * 0.3)
        output_increment = token_increment - input_increment
        agent["tokensUsed"] += token_increment
        agent["inputTokens"] += input_increment
        agent["outputTokens"] += output_increment
        old_progress = agent["progress"]
        agent["progress"] = new_progress
        agent["currentTask"] = self._get_task_for_progress(agent["type"],new_progress)
        self._check_milestone_logs(agent,old_progress,new_progress)
        self._check_checkpoint_creation(agent,old_progress,new_progress)
        self._check_asset_generation(agent,old_progress,new_progress)

        self._emit_event("agent:progress",{
            "agentId":agent["id"],
            "projectId":agent["projectId"],
            "progress":new_progress,
            "currentTask":agent["currentTask"],
            "tokensUsed":agent["tokensUsed"],
            "message":f"進捗: {new_progress}%"
        },agent["projectId"])

        if new_progress >= 100:
            self._complete_agent(agent)

    def _complete_agent(self,agent:Dict):
        now = datetime.now()
        agent["status"] = "completed"
        agent["progress"] = 100
        agent["completedAt"] = now.isoformat()
        agent["currentTask"] = None

        display_name = agent["metadata"].get("displayName",agent["type"])
        self._add_agent_log(agent["id"],"info",f"{display_name}完了",100)
        self._add_system_log(agent["projectId"],"info",agent["type"],f"{display_name}完了")


        self._emit_event("agent:completed",{
            "agentId":agent["id"],
            "projectId":agent["projectId"],
            "agent":agent
        },agent["projectId"])

    def _check_milestone_logs(self,agent:Dict,old_progress:int,new_progress:int):
        milestones = self._get_milestones(agent["type"])

        for milestone_progress,level,message in milestones:
            if old_progress < milestone_progress <= new_progress:
                self._add_agent_log(agent["id"],level,message,milestone_progress)
                if level in ("warn","error"):
                    self._add_system_log(agent["projectId"],level,agent["type"],message)

    def _check_checkpoint_creation(self,agent:Dict,old_progress:int,new_progress:int):
        checkpoint_points = self._get_checkpoint_points(agent["type"])

        for cp_progress,cp_type,cp_title in checkpoint_points:
            if old_progress < cp_progress <= new_progress:

                existing = [c for c in self.checkpoints.values()
                           if c["agentId"] == agent["id"] and c["type"] == cp_type]
                if not existing:
                    self._create_agent_checkpoint(agent,cp_type,cp_title)

    def _create_agent_checkpoint(self,agent:Dict,cp_type:str,title:str):
        checkpoint_id = f"cp-{uuid.uuid4().hex[:8]}"
        now = datetime.now().isoformat()

        content = self._generate_checkpoint_content(agent["type"],cp_type)

        checkpoint = {
            "id":checkpoint_id,
            "projectId":agent["projectId"],
            "agentId":agent["id"],
            "type":cp_type,
            "title":title,
            "description":f"{agent['metadata'].get('displayName', agent['type'])}の成果物を確認してください",
            "output":{
                "type":"document",
                "format":"markdown",
                "content":content
            },
            "status":"pending",
            "feedback":None,
            "resolvedAt":None,
            "createdAt":now,
            "updatedAt":now
        }
        self.checkpoints[checkpoint_id] = checkpoint

        self._add_system_log(agent["projectId"],"info","System",f"チェックポイント作成: {title}")


        self._emit_event("checkpoint:created",{
            "checkpointId":checkpoint_id,
            "projectId":agent["projectId"],
            "agentId":agent["id"],
            "checkpoint":checkpoint
        },agent["projectId"])

    def _check_asset_generation(self,agent:Dict,old_progress:int,new_progress:int):
        asset_points = self._get_asset_points(agent["type"])

        for point_progress,asset_type,asset_name,asset_size in asset_points:
            if old_progress < point_progress <= new_progress:

                project_id = agent["projectId"]
                existing = [a for a in self.assets.get(project_id,[])
                           if a["name"] == asset_name and a["agent"] == agent["metadata"].get("displayName",agent["type"])]
                if not existing:
                    self._create_asset(agent,asset_type,asset_name,asset_size)

    def _create_asset(self,agent:Dict,asset_type:str,name:str,size:str):
        project_id = agent["projectId"]
        if project_id not in self.assets:
            self.assets[project_id] = []


        if asset_type == "image":
            url = f"/assets/{name}"
            thumbnail = f"/thumbnails/{name}"
        elif asset_type == "audio":
            url = f"/assets/{name}"
            thumbnail = None
        else:
            url = None
            thumbnail = None

        asset = {
            "id":f"asset-{uuid.uuid4().hex[:8]}",
            "name":name,
            "type":asset_type,
            "agent":agent["metadata"].get("displayName",agent["type"]),
            "size":size,
            "createdAt":datetime.now().isoformat(),
            "url":url,
            "thumbnail":thumbnail,
            "duration":self._random_duration() if asset_type == "audio" else None,
            "approvalStatus":"pending"
        }
        self.assets[project_id].append(asset)

        display_name = agent["metadata"].get("displayName",agent["type"])
        self._add_system_log(project_id,"info",display_name,f"アセット生成: {name}")

    def _random_duration(self)->str:
        seconds = random.randint(5,180)
        mins = seconds // 60
        secs = seconds % 60
        return f"{mins}:{secs:02d}"

    def _get_asset_points(self,agent_type:str)->List[tuple]:
        assets = {
            "concept":[
                (50,"document","concept_draft.md","12KB"),
                (90,"document","concept_final.md","28KB"),
            ],
            "task_split_1":[
                (50,"document","task_breakdown.md","25KB"),
                (90,"document","iteration_plan.md","35KB"),
            ],
            "concept_detail":[
                (50,"document","concept_detail_draft.md","18KB"),
                (90,"document","concept_detail.md","32KB"),
            ],
            "scenario":[
                (40,"document","story_outline.md","15KB"),
                (70,"document","stage_design.md","22KB"),
                (90,"document","dialogue_script.md","35KB"),
            ],
            "world":[
                (25,"image","bg_grassland.png","1.8MB"),
                (45,"image","bg_cave.png","2.1MB"),
                (60,"image","bg_sky.png","1.6MB"),
                (75,"audio","bgm_grassland.wav","3.2MB"),
                (85,"audio","bgm_cave.wav","2.8MB"),
                (95,"audio","bgm_sky.wav","3.5MB"),
            ],
            "game_design":[
                (30,"document","mechanics_spec.md","18KB"),
                (45,"image","ui_wireframe_01.png","245KB"),
                (55,"image","ui_wireframe_02.png","312KB"),
                (70,"document","sound_spec.md","8KB"),
                (95,"document","game_design.md","42KB"),
            ],
            "tech_spec":[
                (50,"document","tech_spec_draft.md","20KB"),
                (90,"document","tech_spec.md","38KB"),
            ],
            "asset_character":[
                (35,"image","ball_concept.png","156KB"),
                (50,"image","ball_sprite_sheet.png","512KB"),
                (65,"image","guide_character.png","234KB"),
                (80,"image","boss_enemy.png","445KB"),
                (95,"document","character_specs.md","18KB"),
            ],
            "code":[
                (30,"document","main.ts","8KB"),
                (60,"document","utils.ts","4KB"),
                (90,"document","game.ts","12KB"),
            ],
        }
        return assets.get(agent_type,[])

    def _get_generation_type(self,agent_type:str)->str:
        llm_types = ['concept','task_split_1','concept_detail','game_design','tech_spec',
                     'code','event','ui_integration','asset_integration',
                     'unit_test','integration_test']
        image_types = ['asset_character','asset_background','asset_ui','asset_effect']
        audio_types = ['world','asset_bgm','asset_voice','asset_sfx']
        dialogue_types = ['scenario']

        if agent_type in dialogue_types:
            return 'dialogue'
        if agent_type in audio_types:
            return 'audio'
        if agent_type in image_types:
            return 'image'
        return 'llm'

    def _update_project_metrics(self,project_id:str):
        agents = [a for a in self.agents.values() if a["projectId"] == project_id]

        total_input = sum(a.get("inputTokens",0) for a in agents)
        total_output = sum(a.get("outputTokens",0) for a in agents)
        completed_count = len([a for a in agents if a["status"] == "completed"])
        total_count = len(agents)
        total_progress = sum(a["progress"] for a in agents)
        overall_progress = int(total_progress / total_count) if total_count > 0 else 0
        tokens_by_type = {}
        for agent in agents:
            gen_type = self._get_generation_type(agent["type"])
            if gen_type not in tokens_by_type:
                tokens_by_type[gen_type] = {"input":0,"output":0}
            tokens_by_type[gen_type]["input"] += agent.get("inputTokens",0)
            tokens_by_type[gen_type]["output"] += agent.get("outputTokens",0)

        running_agent = next((a for a in agents if a["status"] == "running"),None)
        if running_agent and running_agent["progress"] > 0:
            elapsed = (datetime.now() - datetime.fromisoformat(running_agent["startedAt"])).total_seconds()
            rate = running_agent["progress"] / elapsed if elapsed > 0 else 1
            remaining_progress = 100 - running_agent["progress"]
            remaining_agents = len([a for a in agents if a["status"] == "pending"])
            estimated_remaining = (remaining_progress / rate) + (remaining_agents * 100 / rate) if rate > 0 else 0
        else:
            estimated_remaining = 0

        active_generations = len([a for a in agents if a["status"] == "running"])

        self.metrics[project_id] = {
            "projectId":project_id,
            "totalTokensUsed":total_input + total_output,
            "totalInputTokens":total_input,
            "totalOutputTokens":total_output,
            "estimatedTotalTokens":50000,
            "tokensByType":tokens_by_type,
            "elapsedTimeSeconds":int((datetime.now() - datetime.fromisoformat(self.projects[project_id]["createdAt"])).total_seconds()),
            "estimatedRemainingSeconds":int(estimated_remaining),
            "estimatedEndTime":(datetime.now() + timedelta(seconds=estimated_remaining)).isoformat() if estimated_remaining > 0 else None,
            "completedTasks":completed_count,
            "totalTasks":total_count,
            "progressPercent":overall_progress,
            "currentPhase":1,
            "phaseName":"Phase 1: 企画・設計",
            "activeGenerations":active_generations
        }


        self._emit_event("metrics:update",{
            "projectId":project_id,
            "metrics":self.metrics[project_id]
        },project_id)



    def _get_initial_task(self,agent_type:str)->str:
        tasks = {

            "concept":"[1/4] 初期化: プロジェクト情報を読み込み中",

            "task_split_1":"[1/4] 初期化: コンセプト成果物を分析中",

            "concept_detail":"[1/5] 初期化: コンセプト詳細化を準備中",
            "scenario":"[1/5] 初期化: シナリオ設計を準備中",
            "world":"[1/5] 初期化: 世界観設計を準備中",
            "game_design":"[1/5] 初期化: ゲームデザインを準備中",
            "tech_spec":"[1/5] 初期化: 技術仕様を準備中",

            "task_split_2":"[1/4] 初期化: 設計成果物を分析中",

            "asset_character":"[1/5] 初期化: キャラアセット生成を準備中",
            "asset_background":"[1/5] 初期化: 背景アセット生成を準備中",
            "asset_ui":"[1/5] 初期化: UIアセット生成を準備中",
            "asset_effect":"[1/5] 初期化: エフェクト生成を準備中",
            "asset_bgm":"[1/5] 初期化: BGM生成を準備中",
            "asset_voice":"[1/5] 初期化: ボイス生成を準備中",
            "asset_sfx":"[1/5] 初期化: 効果音生成を準備中",

            "task_split_3":"[1/4] 初期化: アセット成果物を分析中",

            "code":"[1/6] 初期化: コード生成を準備中",
            "event":"[1/5] 初期化: イベント実装を準備中",
            "ui_integration":"[1/5] 初期化: UI統合を準備中",
            "asset_integration":"[1/5] 初期化: アセット統合を準備中",

            "task_split_4":"[1/4] 初期化: 実装成果物を分析中",

            "unit_test":"[1/5] 初期化: 単体テストを準備中",
            "integration_test":"[1/5] 初期化: 統合テストを準備中",
        }
        return tasks.get(agent_type,"[1/3] 初期化: 処理中...")

    def _get_task_for_progress(self,agent_type:str,progress:int)->str:
        tasks = {

            "concept":[
                (0,"[1/4] 初期化: プロジェクト情報を読み込み中"),
                (25,"[2/4] LLM呼び出し: ゲームコンセプトを生成中"),
                (50,"[3/4] 検証: 出力形式をチェック中"),
                (75,"[4/4] ファイル保存: concept.md を保存中"),
            ],

            "task_split_1":[
                (0,"[1/4] 初期化: コンセプト成果物を分析中"),
                (25,"[2/4] LLM呼び出し: タスク分解を生成中"),
                (50,"[3/4] 検証: 依存関係をチェック中"),
                (75,"[4/4] ファイル保存: tasks_1.md を保存中"),
            ],

            "concept_detail":[
                (0,"[1/5] 初期化: コンセプト詳細化を準備中"),
                (20,"[2/5] LLM呼び出し: 詳細コンセプトを生成中"),
                (40,"[3/5] L/Wループ: Leader-Worker確認中"),
                (60,"[4/5] 検証: 詳細内容をチェック中"),
                (80,"[5/5] ファイル保存: concept_detail.md を保存中"),
            ],
            "scenario":[
                (0,"[1/5] 初期化: シナリオ設計を準備中"),
                (20,"[2/5] LLM呼び出し: シナリオ構成を生成中"),
                (40,"[3/5] L/Wループ: Leader-Worker確認中"),
                (60,"[4/5] 検証: シナリオ整合性をチェック中"),
                (80,"[5/5] ファイル保存: scenario.md を保存中"),
            ],
            "world":[
                (0,"[1/5] 初期化: 世界観設計を準備中"),
                (20,"[2/5] LLM呼び出し: 世界観を生成中"),
                (40,"[3/5] L/Wループ: Leader-Worker確認中"),
                (60,"[4/5] 検証: 世界観整合性をチェック中"),
                (80,"[5/5] ファイル保存: world.md を保存中"),
            ],
            "game_design":[
                (0,"[1/5] 初期化: ゲームデザインを準備中"),
                (20,"[2/5] LLM呼び出し: ゲームデザインを生成中"),
                (40,"[3/5] L/Wループ: Leader-Worker確認中"),
                (60,"[4/5] 検証: デザイン整合性をチェック中"),
                (80,"[5/5] ファイル保存: game_design.md を保存中"),
            ],
            "tech_spec":[
                (0,"[1/5] 初期化: 技術仕様を準備中"),
                (20,"[2/5] LLM呼び出し: 技術仕様を生成中"),
                (40,"[3/5] L/Wループ: Leader-Worker確認中"),
                (60,"[4/5] 検証: 仕様整合性をチェック中"),
                (80,"[5/5] ファイル保存: tech_spec.md を保存中"),
            ],

            "task_split_2":[
                (0,"[1/4] 初期化: 設計成果物を分析中"),
                (25,"[2/4] LLM呼び出し: アセットタスク分解を生成中"),
                (50,"[3/4] 検証: 依存関係をチェック中"),
                (75,"[4/4] ファイル保存: tasks_2.md を保存中"),
            ],

            "asset_character":[
                (0,"[1/5] 初期化: キャラアセット生成を準備中"),
                (20,"[2/5] LLM呼び出し: キャラ画像を生成中"),
                (40,"[3/5] ファイル保存: character.png を保存中"),
                (60,"[4/5] 検証: アセット品質をチェック中"),
                (80,"[5/5] 完了: キャラアセット生成完了"),
            ],
            "asset_background":[
                (0,"[1/5] 初期化: 背景アセット生成を準備中"),
                (20,"[2/5] LLM呼び出し: 背景画像を生成中"),
                (40,"[3/5] ファイル保存: background.png を保存中"),
                (60,"[4/5] 検証: アセット品質をチェック中"),
                (80,"[5/5] 完了: 背景アセット生成完了"),
            ],
            "asset_ui":[
                (0,"[1/5] 初期化: UIアセット生成を準備中"),
                (20,"[2/5] LLM呼び出し: UI画像を生成中"),
                (40,"[3/5] ファイル保存: ui_elements.png を保存中"),
                (60,"[4/5] 検証: アセット品質をチェック中"),
                (80,"[5/5] 完了: UIアセット生成完了"),
            ],
            "asset_effect":[
                (0,"[1/5] 初期化: エフェクト生成を準備中"),
                (20,"[2/5] LLM呼び出し: エフェクト画像を生成中"),
                (40,"[3/5] ファイル保存: effect.png を保存中"),
                (60,"[4/5] 検証: アセット品質をチェック中"),
                (80,"[5/5] 完了: エフェクト生成完了"),
            ],
            "asset_bgm":[
                (0,"[1/5] 初期化: BGM生成を準備中"),
                (20,"[2/5] LLM呼び出し: BGMを生成中"),
                (40,"[3/5] ファイル保存: bgm.mp3 を保存中"),
                (60,"[4/5] 検証: 音質をチェック中"),
                (80,"[5/5] 完了: BGM生成完了"),
            ],
            "asset_voice":[
                (0,"[1/5] 初期化: ボイス生成を準備中"),
                (20,"[2/5] LLM呼び出し: ボイスを生成中"),
                (40,"[3/5] ファイル保存: voice.mp3 を保存中"),
                (60,"[4/5] 検証: 音質をチェック中"),
                (80,"[5/5] 完了: ボイス生成完了"),
            ],
            "asset_sfx":[
                (0,"[1/5] 初期化: 効果音生成を準備中"),
                (20,"[2/5] LLM呼び出し: 効果音を生成中"),
                (40,"[3/5] ファイル保存: sfx.mp3 を保存中"),
                (60,"[4/5] 検証: 音質をチェック中"),
                (80,"[5/5] 完了: 効果音生成完了"),
            ],

            "task_split_3":[
                (0,"[1/4] 初期化: アセット成果物を分析中"),
                (25,"[2/4] LLM呼び出し: 実装タスク分解を生成中"),
                (50,"[3/4] 検証: 依存関係をチェック中"),
                (75,"[4/4] ファイル保存: tasks_3.md を保存中"),
            ],

            "code":[
                (0,"[1/6] 初期化: コード生成を準備中"),
                (15,"[2/6] LLM呼び出し: コード生成中 (main.ts)"),
                (30,"[3/6] ファイル保存: main.ts を保存中"),
                (50,"[4/6] L/Wループ: Leader-Worker確認中"),
                (70,"[5/6] LLM呼び出し: コード生成中 (utils.ts)"),
                (85,"[6/6] ファイル保存: utils.ts を保存中"),
            ],
            "event":[
                (0,"[1/5] 初期化: イベント実装を準備中"),
                (20,"[2/5] LLM呼び出し: イベントコードを生成中"),
                (40,"[3/5] L/Wループ: Leader-Worker確認中"),
                (60,"[4/5] ファイル保存: events.ts を保存中"),
                (80,"[5/5] 検証: イベント実装をチェック中"),
            ],
            "ui_integration":[
                (0,"[1/5] 初期化: UI統合を準備中"),
                (20,"[2/5] LLM呼び出し: UIコードを生成中"),
                (40,"[3/5] L/Wループ: Leader-Worker確認中"),
                (60,"[4/5] ファイル保存: ui.tsx を保存中"),
                (80,"[5/5] 検証: UI統合をチェック中"),
            ],
            "asset_integration":[
                (0,"[1/5] 初期化: アセット統合を準備中"),
                (20,"[2/5] LLM呼び出し: 統合コードを生成中"),
                (40,"[3/5] L/Wループ: Leader-Worker確認中"),
                (60,"[4/5] ファイル保存: assets.ts を保存中"),
                (80,"[5/5] 検証: アセット統合をチェック中"),
            ],

            "task_split_4":[
                (0,"[1/4] 初期化: 実装成果物を分析中"),
                (25,"[2/4] LLM呼び出し: テストタスク分解を生成中"),
                (50,"[3/4] 検証: 依存関係をチェック中"),
                (75,"[4/4] ファイル保存: tasks_4.md を保存中"),
            ],

            "unit_test":[
                (0,"[1/5] 初期化: 単体テストを準備中"),
                (20,"[2/5] LLM呼び出し: テストコードを生成中"),
                (40,"[3/5] L/Wループ: Leader-Worker確認中"),
                (60,"[4/5] テスト実行: 単体テストを実行中"),
                (80,"[5/5] ファイル保存: unit_test_result.md を保存中"),
            ],
            "integration_test":[
                (0,"[1/5] 初期化: 統合テストを準備中"),
                (20,"[2/5] LLM呼び出し: テストコードを生成中"),
                (40,"[3/5] L/Wループ: Leader-Worker確認中"),
                (60,"[4/5] テスト実行: 統合テストを実行中"),
                (80,"[5/5] ファイル保存: integration_test_result.md を保存中"),
            ],
        }

        agent_tasks = tasks.get(agent_type,[(0,"[1/3] 初期化: 処理中...")])
        current_task = agent_tasks[0][1]
        for threshold,task in agent_tasks:
            if progress >= threshold:
                current_task = task
        return current_task

    def _get_milestones(self,agent_type:str)->List[tuple]:
        milestones = {

            "concept":[
                (10,"info","プロジェクト情報読み込み完了"),
                (30,"info","ゲームコンセプト生成開始"),
                (60,"info","出力形式チェック完了"),
                (90,"info","concept.md 保存完了"),
            ],

            "task_split_1":[
                (15,"info","コンセプト成果物分析完了"),
                (40,"info","タスク分解生成中"),
                (70,"info","依存関係チェック完了"),
                (90,"info","tasks_1.md 保存完了"),
            ],

            "concept_detail":[
                (15,"info","コンセプト詳細化準備完了"),
                (35,"info","詳細コンセプト生成中"),
                (50,"info","L/Wループ確認中"),
                (70,"info","詳細内容チェック完了"),
                (90,"info","concept_detail.md 保存完了"),
            ],
            "scenario":[
                (15,"info","シナリオ設計準備完了"),
                (35,"info","シナリオ構成生成中"),
                (50,"info","L/Wループ確認中"),
                (70,"info","シナリオ整合性チェック完了"),
                (90,"info","scenario.md 保存完了"),
            ],
            "world":[
                (15,"info","世界観設計準備完了"),
                (35,"info","世界観生成中"),
                (50,"info","L/Wループ確認中"),
                (70,"info","世界観整合性チェック完了"),
                (90,"info","world.md 保存完了"),
            ],
            "game_design":[
                (15,"info","ゲームデザイン準備完了"),
                (35,"info","ゲームデザイン生成中"),
                (50,"info","L/Wループ確認中"),
                (70,"info","デザイン整合性チェック完了"),
                (90,"info","game_design.md 保存完了"),
            ],
            "tech_spec":[
                (15,"info","技術仕様準備完了"),
                (35,"info","技術仕様生成中"),
                (50,"info","L/Wループ確認中"),
                (70,"info","仕様整合性チェック完了"),
                (90,"info","tech_spec.md 保存完了"),
            ],

            "task_split_2":[
                (15,"info","設計成果物分析完了"),
                (40,"info","アセットタスク分解生成中"),
                (70,"info","依存関係チェック完了"),
                (90,"info","tasks_2.md 保存完了"),
            ],

            "asset_character":[
                (15,"info","キャラアセット生成準備完了"),
                (35,"info","キャラ画像生成中"),
                (55,"info","character.png 保存完了"),
                (75,"info","アセット品質チェック完了"),
                (90,"info","キャラアセット生成完了"),
            ],
            "asset_background":[
                (15,"info","背景アセット生成準備完了"),
                (35,"info","背景画像生成中"),
                (55,"info","background.png 保存完了"),
                (75,"info","アセット品質チェック完了"),
                (90,"info","背景アセット生成完了"),
            ],
            "asset_ui":[
                (15,"info","UIアセット生成準備完了"),
                (35,"info","UI画像生成中"),
                (55,"info","ui_elements.png 保存完了"),
                (75,"info","アセット品質チェック完了"),
                (90,"info","UIアセット生成完了"),
            ],
            "asset_effect":[
                (15,"info","エフェクト生成準備完了"),
                (35,"info","エフェクト画像生成中"),
                (55,"info","effect.png 保存完了"),
                (75,"info","アセット品質チェック完了"),
                (90,"info","エフェクト生成完了"),
            ],
            "asset_bgm":[
                (15,"info","BGM生成準備完了"),
                (35,"info","BGM生成中"),
                (55,"info","bgm.mp3 保存完了"),
                (75,"info","音質チェック完了"),
                (90,"info","BGM生成完了"),
            ],
            "asset_voice":[
                (15,"info","ボイス生成準備完了"),
                (35,"info","ボイス生成中"),
                (55,"info","voice.mp3 保存完了"),
                (75,"info","音質チェック完了"),
                (90,"info","ボイス生成完了"),
            ],
            "asset_sfx":[
                (15,"info","効果音生成準備完了"),
                (35,"info","効果音生成中"),
                (55,"info","sfx.mp3 保存完了"),
                (75,"info","音質チェック完了"),
                (90,"info","効果音生成完了"),
            ],

            "task_split_3":[
                (15,"info","アセット成果物分析完了"),
                (40,"info","実装タスク分解生成中"),
                (70,"info","依存関係チェック完了"),
                (90,"info","tasks_3.md 保存完了"),
            ],

            "code":[
                (10,"info","コード生成準備完了"),
                (25,"info","main.ts 生成中"),
                (45,"info","main.ts 保存完了"),
                (55,"info","L/Wループ確認中"),
                (70,"info","utils.ts 生成中"),
                (90,"info","utils.ts 保存完了"),
            ],
            "event":[
                (15,"info","イベント実装準備完了"),
                (35,"info","イベントコード生成中"),
                (50,"info","L/Wループ確認中"),
                (70,"info","events.ts 保存完了"),
                (90,"info","イベント実装完了"),
            ],
            "ui_integration":[
                (15,"info","UI統合準備完了"),
                (35,"info","UIコード生成中"),
                (50,"info","L/Wループ確認中"),
                (70,"info","ui.tsx 保存完了"),
                (90,"info","UI統合完了"),
            ],
            "asset_integration":[
                (15,"info","アセット統合準備完了"),
                (35,"info","統合コード生成中"),
                (50,"info","L/Wループ確認中"),
                (70,"info","assets.ts 保存完了"),
                (90,"info","アセット統合完了"),
            ],

            "task_split_4":[
                (15,"info","実装成果物分析完了"),
                (40,"info","テストタスク分解生成中"),
                (70,"info","依存関係チェック完了"),
                (90,"info","tasks_4.md 保存完了"),
            ],

            "unit_test":[
                (15,"info","単体テスト準備完了"),
                (35,"info","テストコード生成中"),
                (50,"info","L/Wループ確認中"),
                (70,"info","テスト実行完了"),
                (90,"info","unit_test_result.md 保存完了"),
            ],
            "integration_test":[
                (15,"info","統合テスト準備完了"),
                (35,"info","テストコード生成中"),
                (50,"info","L/Wループ確認中"),
                (70,"info","テスト実行完了"),
                (90,"info","integration_test_result.md 保存完了"),
            ],
        }
        return milestones.get(agent_type,[])

    def _get_checkpoint_points(self,agent_type:str)->List[tuple]:
        checkpoints = {

            "concept":[
                (90,"concept_review","ゲームコンセプトの承認"),
            ],

            "task_split_1":[
                (90,"task_review_1","タスク分割1のレビュー"),
            ],

            "concept_detail":[
                (90,"concept_detail_review","コンセプト詳細のレビュー"),
            ],
            "scenario":[
                (90,"scenario_review","シナリオ構成のレビュー"),
            ],
            "world":[
                (90,"world_review","世界観設計のレビュー"),
            ],
            "game_design":[
                (90,"game_design_review","ゲームデザインのレビュー"),
            ],
            "tech_spec":[
                (90,"tech_spec_review","技術仕様のレビュー"),
            ],

            "task_split_2":[
                (90,"task_review_2","タスク分割2のレビュー"),
            ],

            "asset_character":[
                (90,"character_review","キャラアセットのレビュー"),
            ],
            "asset_ui":[
                (90,"ui_review","UIアセットのレビュー"),
            ],

            "task_split_3":[
                (90,"task_review_3","タスク分割3のレビュー"),
            ],

            "code":[
                (90,"code_review","コード実装のレビュー"),
            ],
            "ui_integration":[
                (90,"ui_integration_review","UI統合のレビュー"),
            ],

            "task_split_4":[
                (90,"task_review_4","タスク分割4のレビュー"),
            ],

            "unit_test":[
                (90,"unit_test_review","単体テスト結果のレビュー"),
            ],
            "integration_test":[
                (90,"integration_test_review","統合テスト結果のレビュー"),
            ],
        }
        return checkpoints.get(agent_type,[])

    def _generate_checkpoint_content(self,agent_type:str,cp_type:str)->str:
        contents = {
            "concept_review":"""# ゲームコンセプト

## 概要
ボールを操作してゴールを目指すシンプルなパズルゲーム。

## 特徴
- 物理演算ベースのリアルな挙動
- 全30ステージ
- スコアシステム（タイム + コイン収集）

## ターゲット
全年齢向け、カジュアルゲーマー""",

            "design_review":"""# ゲームデザイン

## 操作方法
- 矢印キー: ボールの移動
- スペースキー: ジャンプ
- R: リスタート

## 物理パラメータ
- 重力: 9.8 m/s²
- 摩擦係数: 0.3
- 反発係数: 0.7""",

            "ui_review":"""# UI設計

## 画面構成
1. タイトル画面
2. ステージ選択
3. ゲームプレイ
4. リザルト画面

## HUD要素
- タイマー（右上）
- コイン数（左上）
- ポーズボタン（右上）""",

            "scenario_review":"""# シナリオ

## ストーリー
小さなボールが大きな冒険に出る物語。
様々な障害物を乗り越えながら、最終目的地を目指す。

## ステージ構成
- ワールド1: 草原（チュートリアル）
- ワールド2: 洞窟
- ワールド3: 空中庭園""",

            "character_review":"""# キャラクターデザイン

## メインキャラクター
- ボール: プレイヤー操作キャラ
- 表情変化あり（喜怒哀楽）

## サブキャラクター
- ガイドキャラ: チュートリアル担当
- ボスキャラ: 各ワールドボス""",

            "world_review":"""# ワールドビルディング

## 世界観
ファンタジー × 物理パズル

## ステージテーマ
- 草原: 明るく開放的
- 洞窟: 暗めでミステリアス
- 空中: 浮遊感と開放感"""
        }
        return contents.get(cp_type,f"# {cp_type}\n\n内容を確認してください。")

    def _add_agent_log(self,agent_id:str,level:str,message:str,progress:Optional[int] = None):
        if agent_id not in self.agent_logs:
            self.agent_logs[agent_id] = []

        log_entry = {
            "id":f"log-{uuid.uuid4().hex[:8]}",
            "timestamp":datetime.now().isoformat(),
            "level":level,
            "message":message,
            "progress":progress,
            "metadata":{}
        }
        self.agent_logs[agent_id].append(log_entry)

    def _add_system_log(self,project_id:str,level:str,source:str,message:str):
        if project_id not in self.system_logs:
            self.system_logs[project_id] = []

        log_entry = {
            "id":f"syslog-{uuid.uuid4().hex[:8]}",
            "timestamp":datetime.now().isoformat(),
            "level":level,
            "source":source,
            "message":message,
            "details":None
        }
        self.system_logs[project_id].append(log_entry)

    def get_projects(self)->List[Dict]:
        with self._lock:
            return list(self.projects.values())

    def get_project(self,project_id:str)->Optional[Dict]:
        with self._lock:
            return self.projects.get(project_id)

    def create_project(self,data:Dict)->Dict:
        with self._lock:
            project_id = f"proj-{uuid.uuid4().hex[:8]}"
            now = datetime.now().isoformat()
            project = {
                "id":project_id,
                "name":data.get("name","新規プロジェクト"),
                "description":data.get("description",""),
                "concept":data.get("concept",{}),
                "status":"draft",
                "currentPhase":1,
                "state":{},
                "config":data.get("config",{}),
                "createdAt":now,
                "updatedAt":now
            }
            self.projects[project_id] = project
            self.system_logs[project_id] = []
            return project

    def update_project(self,project_id:str,data:Dict)->Optional[Dict]:
        with self._lock:
            if project_id not in self.projects:
                return None
            project = self.projects[project_id]
            project.update(data)
            project["updatedAt"] = datetime.now().isoformat()
            return project

    def delete_project(self,project_id:str)->bool:
        with self._lock:
            if project_id in self.projects:
                del self.projects[project_id]
                self.agents = {k:v for k,v in self.agents.items() if v["projectId"] != project_id}
                self.checkpoints = {k:v for k,v in self.checkpoints.items() if v["projectId"] != project_id}
                if project_id in self.metrics:
                    del self.metrics[project_id]
                if project_id in self.system_logs:
                    del self.system_logs[project_id]
                return True
            return False

    def start_project(self,project_id:str)->Optional[Dict]:
        with self._lock:
            project = self.projects.get(project_id)
            if not project:
                return None

            if project["status"] in ("draft","paused"):
                project["status"] = "running"
                project["updatedAt"] = datetime.now().isoformat()
                self._add_system_log(project_id,"info","System","プロジェクト開始")
            return project

    def pause_project(self,project_id:str)->Optional[Dict]:
        with self._lock:
            project = self.projects.get(project_id)
            if not project:
                return None

            if project["status"] == "running":
                project["status"] = "paused"
                project["updatedAt"] = datetime.now().isoformat()
                self._add_system_log(project_id,"info","System","プロジェクト一時停止")
            return project

    def resume_project(self,project_id:str)->Optional[Dict]:
        with self._lock:
            project = self.projects.get(project_id)
            if not project:
                return None

            if project["status"] == "paused":
                project["status"] = "running"
                project["updatedAt"] = datetime.now().isoformat()
                self._add_system_log(project_id,"info","System","プロジェクト再開")
            return project

    def initialize_project(self,project_id:str)->Optional[Dict]:
        with self._lock:
            project = self.projects.get(project_id)
            if not project:
                return None

            now = datetime.now()


            project["status"] = "draft"
            project["currentPhase"] = 1
            project["updatedAt"] = now.isoformat()


            self.agents = {k:v for k,v in self.agents.items() if v["projectId"] != project_id}
            self.agent_logs = {k:v for k,v in self.agent_logs.items() if not k.startswith(f"agent-{project_id}")}




            agents_data = [

                {"type":"concept","name":"コンセプト","phase":0},

                {"type":"task_split_1","name":"タスク分割1","phase":1},

                {"type":"concept_detail","name":"コンセプト詳細","phase":2},
                {"type":"scenario","name":"シナリオ","phase":2},
                {"type":"world","name":"世界観","phase":2},
                {"type":"game_design","name":"ゲームデザイン","phase":2},
                {"type":"tech_spec","name":"技術仕様","phase":2},

                {"type":"task_split_2","name":"タスク分割2","phase":3},

                {"type":"asset_character","name":"キャラ","phase":4},
                {"type":"asset_background","name":"背景","phase":4},
                {"type":"asset_ui","name":"UI","phase":4},
                {"type":"asset_effect","name":"エフェクト","phase":4},
                {"type":"asset_bgm","name":"BGM","phase":4},
                {"type":"asset_voice","name":"ボイス","phase":4},
                {"type":"asset_sfx","name":"効果音","phase":4},

                {"type":"task_split_3","name":"タスク分割3","phase":5},

                {"type":"code","name":"コード","phase":6},
                {"type":"event","name":"イベント","phase":6},
                {"type":"ui_integration","name":"UI統合","phase":6},
                {"type":"asset_integration","name":"アセット統合","phase":6},

                {"type":"task_split_4","name":"タスク分割4","phase":7},

                {"type":"unit_test","name":"単体テスト","phase":8},
                {"type":"integration_test","name":"統合テスト","phase":8},
            ]

            for data in agents_data:
                agent_id = f"agent-{project_id}-{data['type']}"
                self.agents[agent_id] = {
                    "id":agent_id,
                    "projectId":project_id,
                    "type":data["type"],
                    "phase":data["phase"],
                    "status":"pending",
                    "progress":0,
                    "currentTask":None,
                    "tokensUsed":0,
                    "inputTokens":0,
                    "outputTokens":0,
                    "startedAt":None,
                    "completedAt":None,
                    "error":None,
                    "parentAgentId":None,
                    "metadata":{"displayName":data["name"]},
                    "createdAt":now.isoformat()
                }
                self.agent_logs[agent_id] = []


            self.checkpoints = {k:v for k,v in self.checkpoints.items() if v["projectId"] != project_id}


            self.system_logs[project_id] = []


            testdata_path = get_testdata_path()
            real_assets = scan_all_testdata(testdata_path)
            self.assets[project_id] = real_assets


            self.metrics[project_id] = {
                "projectId":project_id,
                "totalTokensUsed":0,
                "estimatedTotalTokens":50000,
                "elapsedTimeSeconds":0,
                "estimatedRemainingSeconds":0,
                "estimatedEndTime":None,
                "completedTasks":0,
                "totalTasks":6,
                "progressPercent":0,
                "currentPhase":1,
                "phaseName":"Phase 1: 企画・設計",
                "activeGenerations":0
            }

            self._add_system_log(project_id,"info","System","プロジェクト初期化完了")
            print(f"[TestDataStore] Project {project_id} initialized")
            return project

    def get_agents_by_project(self,project_id:str)->List[Dict]:
        with self._lock:
            return [a for a in self.agents.values() if a["projectId"] == project_id]

    def get_agent(self,agent_id:str)->Optional[Dict]:
        with self._lock:
            return self.agents.get(agent_id)

    def get_agent_logs(self,agent_id:str)->List[Dict]:
        with self._lock:
            return self.agent_logs.get(agent_id,[])

    def create_agent(self,project_id:str,agent_type:str)->Dict:
        with self._lock:
            agent_id = f"agent-{uuid.uuid4().hex[:8]}"
            now = datetime.now().isoformat()
            agent = {
                "id":agent_id,
                "projectId":project_id,
                "type":agent_type,
                "status":"pending",
                "progress":0,
                "currentTask":None,
                "tokensUsed":0,
                "inputTokens":0,
                "outputTokens":0,
                "startedAt":None,
                "completedAt":None,
                "error":None,
                "parentAgentId":None,
                "metadata":{},
                "createdAt":now
            }
            self.agents[agent_id] = agent
            self.agent_logs[agent_id] = []
            return agent

    def update_agent(self,agent_id:str,data:Dict)->Optional[Dict]:
        with self._lock:
            if agent_id not in self.agents:
                return None
            self.agents[agent_id].update(data)
            return self.agents[agent_id]

    def add_agent_log(self,agent_id:str,level:str,message:str,progress:Optional[int] = None):
        with self._lock:
            self._add_agent_log(agent_id,level,message,progress)

    def get_checkpoints_by_project(self,project_id:str)->List[Dict]:
        with self._lock:
            return [c for c in self.checkpoints.values() if c["projectId"] == project_id]

    def get_checkpoint(self,checkpoint_id:str)->Optional[Dict]:
        with self._lock:
            return self.checkpoints.get(checkpoint_id)

    def create_checkpoint(self,project_id:str,agent_id:str,data:Dict)->Dict:
        with self._lock:
            checkpoint_id = f"cp-{uuid.uuid4().hex[:8]}"
            now = datetime.now().isoformat()
            checkpoint = {
                "id":checkpoint_id,
                "projectId":project_id,
                "agentId":agent_id,
                "type":data.get("type","review"),
                "title":data.get("title","レビュー依頼"),
                "description":data.get("description"),
                "output":data.get("output",{}),
                "status":"pending",
                "feedback":None,
                "resolvedAt":None,
                "createdAt":now,
                "updatedAt":now
            }
            self.checkpoints[checkpoint_id] = checkpoint
            return checkpoint

    def resolve_checkpoint(self,checkpoint_id:str,resolution:str,feedback:Optional[str] = None)->Optional[Dict]:
        with self._lock:
            if checkpoint_id not in self.checkpoints:
                return None
            checkpoint = self.checkpoints[checkpoint_id]
            now = datetime.now().isoformat()
            checkpoint["status"] = resolution
            checkpoint["feedback"] = feedback
            checkpoint["resolvedAt"] = now
            checkpoint["updatedAt"] = now


            project_id = checkpoint["projectId"]
            status_text = {"approved":"承認","rejected":"却下","revision_requested":"修正要求"}
            self._add_system_log(project_id,"info","System",
                               f"チェックポイント{status_text.get(resolution, resolution)}: {checkpoint['title']}")


            if resolution == "approved":
                self._check_phase_advancement(project_id)

            return checkpoint

    def _check_phase_advancement(self,project_id:str):
        """Check if we should advance to the next phase"""
        project = self.projects.get(project_id)
        if not project:
            return

        current_phase = project.get("currentPhase",1)
        project_checkpoints = [c for c in self.checkpoints.values() if c["projectId"] == project_id]


        phase1_types = {"concept_review","design_review","scenario_review","character_review","world_review","task_review"}

        if current_phase == 1:

            phase1_checkpoints = [c for c in project_checkpoints if c["type"] in phase1_types]
            if phase1_checkpoints and all(c["status"] == "approved" for c in phase1_checkpoints):

                project["currentPhase"] = 2
                project["updatedAt"] = datetime.now().isoformat()


                if project_id in self.metrics:
                    self.metrics[project_id]["currentPhase"] = 2
                    self.metrics[project_id]["phaseName"] = "Phase 2: 実装"

                self._add_system_log(project_id,"info","System","Phase 2: 実装 に移行しました")
                print(f"[TestDataStore] Project {project_id} advanced to Phase 2")

    def get_system_logs(self,project_id:str)->List[Dict]:
        with self._lock:
            return self.system_logs.get(project_id,[])

    def get_assets_by_project(self,project_id:str)->List[Dict]:
        with self._lock:
            return self.assets.get(project_id,[])

    def update_asset(self,project_id:str,asset_id:str,data:Dict)->Optional[Dict]:
        with self._lock:
            assets = self.assets.get(project_id,[])
            for asset in assets:
                if asset["id"] == asset_id:
                    asset.update(data)
                    return asset
            return None

    def get_project_metrics(self,project_id:str)->Optional[Dict]:
        with self._lock:
            return self.metrics.get(project_id)

    def update_project_metrics(self,project_id:str,data:Dict)->Dict:
        with self._lock:
            if project_id not in self.metrics:
                self.metrics[project_id] = {
                    "projectId":project_id,
                    "totalTokensUsed":0,
                    "estimatedTotalTokens":50000,
                    "elapsedTimeSeconds":0,
                    "estimatedRemainingSeconds":0,
                    "estimatedEndTime":None,
                    "completedTasks":0,
                    "totalTasks":0,
                    "progressPercent":0,
                    "currentPhase":1,
                    "phaseName":"Phase 1: 企画・設計",
                    "activeGenerations":0
                }
            self.metrics[project_id].update(data)
            return self.metrics[project_id]

    def add_subscription(self,project_id:str,sid:str):
        with self._lock:
            if project_id not in self.subscriptions:
                self.subscriptions[project_id] = set()
            self.subscriptions[project_id].add(sid)

    def remove_subscription(self,project_id:str,sid:str):
        with self._lock:
            if project_id in self.subscriptions:
                self.subscriptions[project_id].discard(sid)

    def remove_all_subscriptions(self,sid:str):
        with self._lock:
            for project_id in self.subscriptions:
                self.subscriptions[project_id].discard(sid)

    def get_subscribers(self,project_id:str)->set:
        with self._lock:
            return self.subscriptions.get(project_id,set()).copy()

    def get_quality_settings(self,project_id:str)->Dict[str,QualityCheckConfig]:
        with self._lock:
            if project_id not in self.quality_settings:

                self.quality_settings[project_id] = get_default_quality_settings()
            return self.quality_settings[project_id].copy()

    def set_quality_setting(
        self,project_id:str,agent_type:str,config:QualityCheckConfig
    )->None:
        with self._lock:
            if project_id not in self.quality_settings:
                self.quality_settings[project_id] = get_default_quality_settings()
            self.quality_settings[project_id][agent_type] = config

    def reset_quality_settings(self,project_id:str)->None:
        with self._lock:
            self.quality_settings[project_id] = get_default_quality_settings()

    def get_quality_setting_for_agent(self,project_id:str,agent_type:str)->QualityCheckConfig:
        settings = self.get_quality_settings(project_id)
        return settings.get(agent_type,QualityCheckConfig())



    def get_interventions_by_project(self,project_id:str)->List[Dict]:
        with self._lock:
            return [i for i in self.interventions.values() if i["projectId"] == project_id]

    def get_intervention(self,intervention_id:str)->Optional[Dict]:
        with self._lock:
            return self.interventions.get(intervention_id)

    def create_intervention(
        self,
        project_id:str,
        target_type:str,
        target_agent_id:Optional[str],
        priority:str,
        message:str,
        attached_file_ids:List[str]
    )->Dict:
        with self._lock:
            intervention_id = f"int-{uuid.uuid4().hex[:8]}"
            now = datetime.now().isoformat()
            intervention = {
                "id":intervention_id,
                "projectId":project_id,
                "targetType":target_type,
                "targetAgentId":target_agent_id,
                "priority":priority,
                "message":message,
                "attachedFileIds":attached_file_ids,
                "status":"pending",
                "createdAt":now,
                "deliveredAt":None,
                "acknowledgedAt":None,
                "processedAt":None
            }
            self.interventions[intervention_id] = intervention


            target_desc = "全エージェント" if target_type == "all" else f"エージェント {target_agent_id}"
            priority_desc = "緊急" if priority == "urgent" else "通常"
            self._add_system_log(
                project_id,"info","Human",
                f"[{priority_desc}] {target_desc}への介入: {message[:50]}..."
            )

            return intervention

    def acknowledge_intervention(self,intervention_id:str)->Optional[Dict]:
        with self._lock:
            if intervention_id not in self.interventions:
                return None
            intervention = self.interventions[intervention_id]
            now = datetime.now().isoformat()
            intervention["status"] = "acknowledged"
            intervention["acknowledgedAt"] = now
            return intervention

    def process_intervention(self,intervention_id:str)->Optional[Dict]:
        with self._lock:
            if intervention_id not in self.interventions:
                return None
            intervention = self.interventions[intervention_id]
            now = datetime.now().isoformat()
            intervention["status"] = "processed"
            intervention["processedAt"] = now


            self._add_system_log(
                intervention["projectId"],"info","System",
                f"介入処理完了: {intervention['message'][:30]}..."
            )

            return intervention

    def deliver_intervention(self,intervention_id:str)->Optional[Dict]:
        with self._lock:
            if intervention_id not in self.interventions:
                return None
            intervention = self.interventions[intervention_id]
            now = datetime.now().isoformat()
            intervention["status"] = "delivered"
            intervention["deliveredAt"] = now
            return intervention



    def get_uploaded_files_by_project(self,project_id:str)->List[Dict]:
        with self._lock:
            return [f for f in self.uploaded_files.values() if f["projectId"] == project_id]

    def get_uploaded_file(self,file_id:str)->Optional[Dict]:
        with self._lock:
            return self.uploaded_files.get(file_id)

    def create_uploaded_file(
        self,
        project_id:str,
        filename:str,
        original_filename:str,
        mime_type:str,
        category:str,
        size_bytes:int,
        description:str
    )->Dict:
        with self._lock:
            file_id = f"file-{uuid.uuid4().hex[:8]}"
            now = datetime.now().isoformat()
            uploaded_file = {
                "id":file_id,
                "projectId":project_id,
                "filename":filename,
                "originalFilename":original_filename,
                "mimeType":mime_type,
                "category":category,
                "sizeBytes":size_bytes,
                "status":"ready",
                "description":description,
                "uploadedAt":now,
                "url":f"/uploads/{project_id}/{filename}"
            }
            self.uploaded_files[file_id] = uploaded_file


            self._add_system_log(
                project_id,"info","Upload",
                f"ファイルアップロード: {original_filename} ({category})"
            )

            return uploaded_file

    def delete_uploaded_file(self,file_id:str)->bool:
        with self._lock:
            if file_id in self.uploaded_files:
                del self.uploaded_files[file_id]
                return True
            return False

    def update_uploaded_file(self,file_id:str,data:Dict)->Optional[Dict]:
        with self._lock:
            if file_id not in self.uploaded_files:
                return None
            self.uploaded_files[file_id].update(data)
            return self.uploaded_files[file_id]
