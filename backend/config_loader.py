"""
設定ファイルローダー
JSON/YAML設定ファイルを読み込み、アプリケーション全体で使用可能にする
"""
import json
import os
from typing import Dict,Any,Optional,Set,List
from pathlib import Path
import yaml


_config_cache:Dict[str,Any]={}
_config_dir:Optional[Path]=None
_principle_cache:Dict[str,str]={}


def get_config_dir()->Path:
    global _config_dir
    if _config_dir is None:
        _config_dir=Path(__file__).parent/"config"
    return _config_dir


def load_json_config(filename:str,use_cache:bool=True)->Dict[str,Any]:
    global _config_cache

    if use_cache and filename in _config_cache:
        return _config_cache[filename]

    config_path=get_config_dir()/filename
    if not config_path.exists():
        raise FileNotFoundError(f"Config file not found: {config_path}")

    with open(config_path,"r",encoding="utf-8") as f:
        data=json.load(f)

    if use_cache:
        _config_cache[filename]=data

    return data


def load_yaml_config(filename:str,use_cache:bool=True)->Dict[str,Any]:
    global _config_cache

    if use_cache and filename in _config_cache:
        return _config_cache[filename]

    config_path=get_config_dir()/filename
    if not config_path.exists():
        raise FileNotFoundError(f"Config file not found: {config_path}")

    with open(config_path,"r",encoding="utf-8") as f:
        data=yaml.safe_load(f)

    if use_cache:
        _config_cache[filename]=data

    return data or {}


def reload_config(filename:Optional[str]=None):
    """設定キャッシュをクリアして再読み込み"""
    global _config_cache
    if filename:
        _config_cache.pop(filename,None)
    else:
        _config_cache.clear()








def get_project_options_config()->Dict[str,Any]:
    """プロジェクトオプション設定を取得"""
    return load_json_config("project_options.json")


def get_platforms()->List[Dict[str,str]]:
    """プラットフォーム選択肢を取得"""
    config=get_project_options_config()
    return config.get("platforms",[])


def get_scopes()->List[Dict[str,str]]:
    """スコープ選択肢を取得"""
    config=get_project_options_config()
    return config.get("scopes",[])


def get_llm_providers()->List[Dict[str,Any]]:
    """LLMプロバイダー選択肢を取得"""
    config=get_project_options_config()
    return config.get("llmProviders",[])


def get_project_defaults()->Dict[str,str]:
    """プロジェクトのデフォルト値を取得"""
    config=get_project_options_config()
    return config.get("defaults",{})




def get_file_extensions_config()->Dict[str,Any]:
    """ファイル拡張子設定を取得"""
    return load_json_config("file_extensions.json")


def get_extensions_for_category(category:str)->Set[str]:
    """カテゴリに属する拡張子のセットを取得"""
    config=get_file_extensions_config()
    categories=config.get("categories",{})
    category_config=categories.get(category,{})
    return set(category_config.get("extensions",[]))


def get_all_extension_categories()->Dict[str,Set[str]]:
    """全カテゴリの拡張子マップを取得"""
    config=get_file_extensions_config()
    categories=config.get("categories",{})
    return {
        cat:set(data.get("extensions",[]))
        for cat,data in categories.items()
    }


def get_scan_directories()->List[str]:
    """スキャン対象ディレクトリ一覧を取得"""
    config=get_file_extensions_config()
    return config.get("scanDirectories",["image","mp3","movie"])




def get_agent_definitions_config()->Dict[str,Any]:
    """エージェント定義設定を取得（agents.yamlから生成）"""
    config=get_agents_config()
    agents=config.get("agents",{})
    agents_out={}
    for agent_id,agent in agents.items():
        agents_out[agent_id]={
            "label":agent.get("label",""),
            "shortLabel":agent.get("short_label",""),
            "phase":agent.get("phase",0),
            "speechBubble":agent.get("speech_bubble",""),
        }
    high_cost_agents=[k for k,v in agents.items() if v.get("high_cost",False)]
    quality_defaults=config.get("quality_check_defaults",{"max_retries":3})
    phases={}
    for phase_id,phase in config.get("phases",{}).items():
        phases[phase_id]=phase.get("agents",[])
    display_names={k:v.get("label","") for k,v in agents.items()}
    return {
        "agents":agents_out,
        "highCostAgents":high_cost_agents,
        "qualityCheckDefaults":{"enabled":True,"maxRetries":quality_defaults.get("max_retries",3)},
        "phases":phases,
        "displayNames":display_names,
    }


def get_agent_definitions()->Dict[str,Dict[str,Any]]:
    """エージェント定義を取得"""
    config=get_agent_definitions_config()
    return config.get("agents",{})


def get_high_cost_agents()->Set[str]:
    """高コストエージェントのセットを取得"""
    config=get_agent_definitions_config()
    return set(config.get("highCostAgents",[]))


def get_agent_phases()->Dict[str,List[str]]:
    """エージェントフェーズ定義を取得"""
    config=get_agent_definitions_config()
    return config.get("phases",{})


def get_agent_display_names()->Dict[str,str]:
    """エージェント表示名を取得"""
    config=get_agent_definitions_config()
    return config.get("displayNames",{})


def get_quality_check_defaults()->Dict[str,Any]:
    config=get_agent_definitions_config()
    return config.get("qualityCheckDefaults",{"enabled":True,"maxRetries":3})


def get_project_settings_config()->Dict[str,Any]:
    return load_yaml_config("project_settings.yaml")


def get_output_settings_defaults()->Dict[str,Any]:
    config=get_project_settings_config()
    return config.get("output",{"default_dir":"./output"})


def get_websocket_config()->Dict[str,Any]:
    config=get_project_settings_config()
    return config.get("websocket",{})


def get_cost_settings_defaults()->Dict[str,Any]:
    config=get_project_settings_config()
    return config.get("cost",{})


def get_agent_service_map()->Dict[str,str]:
    config=get_agents_config()
    agents=config.get("agents",{})
    return {k:v.get("output_type","llm") for k,v in agents.items()}


def get_ai_providers_config()->Dict[str,Any]:
    return load_yaml_config("ai_providers.yaml")


def get_pricing_config()->Dict[str,Any]:
    config=get_ai_providers_config()
    currency=config.get("pricing",{}).get("currency","USD")
    units=config.get("pricing",{}).get("units",{})
    models={}
    for provider_id,provider in config.get("providers",{}).items():
        for model in provider.get("models",[]):
            models[model["id"]]={
                "provider":provider_id,
                "pricing":model.get("pricing",{})
            }
    return {"currency":currency,"units":units,"models":models}


def get_agents_config()->Dict[str,Any]:
    return load_yaml_config("agents.yaml")


def get_checkpoints_config()->Dict[str,Any]:
    return load_yaml_config("checkpoints.yaml")


def get_messages_config()->Dict[str,Any]:
    return load_yaml_config("messages.yaml")


def get_token_budget_settings()->Dict[str,Any]:
    config=get_agents_config()
    return config.get("token_budget",{})


def get_context_policy_settings()->Dict[str,Any]:
    config=get_agents_config()
    return config.get("context_policy_settings",{})


def get_agent_types()->List[str]:
    return list(get_agents_config().get("agents",{}).keys())


def get_workflow_dependencies()->Dict[str,List[str]]:
    raw=get_agents_config().get("workflow_dependencies",{})
    result={}
    for agent,deps in raw.items():
        if isinstance(deps,list):
            result[agent]=deps
        elif isinstance(deps,dict):
            result[agent]=deps.get("depends_on",[])
    return result


def is_dag_execution_enabled()->bool:
    config=get_agents_config()
    dag_config=config.get("dag_execution",{})
    return dag_config.get("enabled",True)


def get_dag_execution_settings()->Dict[str,Any]:
    config=get_agents_config()
    return config.get("dag_execution",{"enabled":True})


def get_advanced_quality_check_settings()->Dict[str,Any]:
    config=get_agents_config()
    return config.get("advanced_quality_check",{
        "quality_threshold":0.6,
        "escalation":{
            "enabled":True,
            "tier2_score_min":0.5,
            "tier2_score_max":0.7
        }
    })


def get_tool_execution_limits()->Dict[str,Any]:
    config=get_agents_config()
    return config.get("tool_execution_limits",{
        "max_iterations":50,
        "timeout_seconds":300,
        "loop_detection_threshold":3
    })


def get_concurrent_limits()->Dict[str,Any]:
    config=get_project_settings_config()
    return config.get("concurrent_limits",{
        "default_max_concurrent":5,
        "provider_overrides":{}
    })


def get_temperature_defaults()->Dict[str,float]:
    config=get_agents_config()
    return config.get("temperature_defaults",{
        "leader":0.7,
        "worker":0.5,
        "splitter":0.3,
        "integrator":0.4,
        "tester":0.3,
        "default":0.7
    })


def get_workflow_context_policy(agent_type:str)->Dict[str,Any]:
    raw=get_agents_config().get("workflow_dependencies",{})
    entry=raw.get(agent_type)
    if isinstance(entry,dict):
        context_from=entry.get("context_from",{})
        result={}
        for dep_key,policy in context_from.items():
            if isinstance(policy,str):
                result[dep_key]={"level":policy}
            elif isinstance(policy,dict):
                result[dep_key]=policy
            else:
                result[dep_key]={"level":"full"}
        return result
    return {}


def get_agent_max_tokens(agent_type:str)->Optional[int]:
    config=get_agents_config()
    agents=config.get("agents",{})
    agent=agents.get(agent_type,{})
    return agent.get("max_tokens")


def get_agent_temperature(agent_type:str)->float:
    config=get_agents_config()
    agents=config.get("agents",{})
    agent=agents.get(agent_type,{})
    if"temperature" in agent:
        return float(agent["temperature"])
    role=agent.get("role","default")
    temp_defaults=config.get("temperature_defaults",{})
    return float(temp_defaults.get(role,temp_defaults.get("default",0.7)))


def get_checkpoint_category_map()->Dict[str,str]:
    return get_checkpoints_config().get("category_map",{})


def get_auto_approval_rules()->List[Dict[str,Any]]:
    return get_checkpoints_config().get("auto_approval_rules",[])


def get_status_labels()->Dict[str,str]:
    return get_checkpoints_config().get("status_labels",{})


def get_resolution_labels()->Dict[str,str]:
    return get_checkpoints_config().get("resolution_labels",{})


def get_initial_task(agent_type:str)->str:
    config=get_messages_config()
    tasks=config.get("initial_tasks",{})
    return tasks.get(agent_type,tasks.get("default","[1/3] 初期化: 処理中..."))


def get_task_for_progress(agent_type:str,progress:int)->str:
    config=get_messages_config()
    progress_tasks=config.get("progress_tasks",{})
    agent_tasks=progress_tasks.get(agent_type,[])
    if not agent_tasks:
        return get_initial_task(agent_type)
    current_task=agent_tasks[0].get("task","")
    for item in agent_tasks:
        if progress>=item.get("progress",0):
            current_task=item.get("task","")
    return current_task


def get_milestones(agent_type:str)->List[tuple]:
    config=get_messages_config()
    milestones=config.get("milestones",{})
    agent_milestones=milestones.get(agent_type,[])
    return [(m.get("progress",0),m.get("level","info"),m.get("message","")) for m in agent_milestones]


def get_agent_definitions_from_yaml()->Dict[str,Dict[str,Any]]:
    config=get_agents_config()
    agents=config.get("agents",{})
    result={}
    for agent_id,agent in agents.items():
        result[agent_id]={
            "label":agent.get("label",""),
            "shortLabel":agent.get("short_label",""),
            "phase":agent.get("phase",0),
            "speechBubble":agent.get("speech_bubble",""),
        }
    return result


def get_high_cost_agents_from_yaml()->Set[str]:
    config=get_agents_config()
    agents=config.get("agents",{})
    return {k for k,v in agents.items() if v.get("high_cost",False)}


def get_quality_check_defaults_from_yaml()->Dict[str,bool]:
    config=get_agents_config()
    agents=config.get("agents",{})
    return {k:v.get("quality_check",True) for k,v in agents.items()}


def get_agent_phases_from_yaml()->Dict[str,List[str]]:
    config=get_agents_config()
    phases=config.get("phases",{})
    result={}
    for phase_id,phase in phases.items():
        result[phase_id]=phase.get("agents",[])
    return result


def get_agent_display_names_from_yaml()->Dict[str,str]:
    config=get_agents_config()
    agents=config.get("agents",{})
    return {k:v.get("label","") for k,v in agents.items()}




def get_ui_phases()->List[Dict[str,Any]]:
    config=get_agents_config()
    return config.get("ui_phases",[])


def get_agent_asset_mapping()->Dict[str,List[str]]:
    config=get_agents_config()
    return config.get("agent_asset_mapping",{})


def get_agent_status_labels()->Dict[str,str]:
    return get_checkpoints_config().get("agent_status_labels",{})


def get_approval_status_labels()->Dict[str,str]:
    return get_checkpoints_config().get("approval_status_labels",{})


def get_asset_type_labels()->Dict[str,str]:
    return get_checkpoints_config().get("asset_type_labels",{})


def get_role_labels()->Dict[str,str]:
    return get_checkpoints_config().get("role_labels",{})


def get_checkpoint_type_labels()->Dict[str,str]:
    return get_checkpoints_config().get("checkpoint_type_labels",{})


def get_agent_roles()->Dict[str,str]:
    config=get_agents_config()
    agents=config.get("agents",{})
    return {k:v.get("role","worker") for k,v in agents.items()}


_prompt_cache:Dict[str,str]={}


def load_prompt(agent_type:str)->str:
    global _prompt_cache
    if agent_type in _prompt_cache:
        return _prompt_cache[agent_type]
    prompts_dir=get_config_dir()/"prompts"
    prompt_file=prompts_dir/f"{agent_type}.md"
    if not prompt_file.exists():
        prompt_file=prompts_dir/"_default.md"
    if not prompt_file.exists():
        return""
    with open(prompt_file,"r",encoding="utf-8") as f:
        content=f.read()
    _prompt_cache[agent_type]=content
    return content


def get_all_prompts()->Dict[str,str]:
    prompts_dir=get_config_dir()/"prompts"
    if not prompts_dir.exists():
        return {}
    result={}
    for prompt_file in prompts_dir.glob("*.md"):
        if prompt_file.name.startswith("_"):
            continue
        agent_type=prompt_file.stem
        result[agent_type]=load_prompt(agent_type)
    return result


def clear_prompt_cache()->None:
    global _prompt_cache
    _prompt_cache.clear()


def get_mock_data_config()->Dict[str,Any]:
    return load_yaml_config("mock_data.yaml")


def get_mock_skill_sequences(agent_type:str)->List[Dict[str,Any]]:
    config=get_mock_data_config()
    sequences=config.get("mock_skill_sequences",{})
    return sequences.get(agent_type,sequences.get("default",[]))


def load_principle(name:str)->str:
    global _principle_cache
    if name in _principle_cache:
        return _principle_cache[name]
    principle_path=get_config_dir()/"principles"/f"{name}.md"
    if not principle_path.exists():
        return""
    with open(principle_path,"r",encoding="utf-8") as f:
        content=f.read()
    _principle_cache[name]=content
    return content


def get_agent_principles(agent_type:str,overrides:Optional[Dict[str,List[str]]]=None)->List[str]:
    if overrides and agent_type in overrides:
        return list(overrides[agent_type])
    config=get_agents_config()
    mapping=config.get("agent_principles",{})
    principles=mapping.get(agent_type)
    if principles is None:
        principles=mapping.get("_default",[])
    return principles


def load_principles_for_agent(agent_type:str,enabled_principles:Optional[List[str]]=None,principle_overrides:Optional[Dict[str,List[str]]]=None)->str:
    principle_names=get_agent_principles(agent_type,overrides=principle_overrides)
    if enabled_principles is not None:
        principle_names=[p for p in principle_names if p in enabled_principles]
    if not principle_names:
        return""
    config=get_agents_config()
    settings=config.get("principle_settings",{})
    max_chars=settings.get("max_chars_per_agent",12000)
    parts=[]
    total_len=0
    for name in principle_names:
        content=load_principle(name)
        if not content:
            continue
        if total_len+len(content)>max_chars:
            compact=_extract_compact_principle(content)
            if total_len+len(compact)<=max_chars:
                parts.append(compact)
                total_len+=len(compact)
        else:
            parts.append(content)
            total_len+=len(content)
    return"\n\n---\n\n".join(parts)


def _extract_compact_principle(content:str)->str:
    import re
    lines=content.split("\n")
    result=[]
    in_overview=False
    in_rubric=False
    for line in lines:
        if line.startswith("# 原則:"):
            result.append(line)
            continue
        if line.strip()=="## 概要":
            in_overview=True
            result.append(line)
            continue
        if in_overview:
            if line.startswith("## ") and line.strip()!="## 概要":
                in_overview=False
            else:
                result.append(line)
                continue
        if line.strip()=="## 評価ルーブリック":
            in_rubric=True
            result.append(line)
            continue
        if in_rubric:
            if line.startswith("## ") and line.strip()!="## 評価ルーブリック":
                in_rubric=False
            else:
                result.append(line)
                continue
    return"\n".join(result)


def clear_principle_cache()->None:
    global _principle_cache
    _principle_cache.clear()


def get_principle_settings()->Dict[str,Any]:
    config=get_agents_config()
    return config.get("principle_settings",{})


def get_available_principles()->List[Dict[str,str]]:
    principles_dir=get_config_dir()/"principles"
    if not principles_dir.exists():
        return[]
    result=[]
    for f in principles_dir.glob("*.md"):
        name=f.stem
        content=load_principle(name)
        title=name
        description=""
        for line in content.split("\n"):
            if line.startswith("# 原則:"):
                title=line.replace("# 原則:","").strip()
            elif line.strip() and not line.startswith("#") and not description:
                description=line.strip()
                break
        result.append({"id":name,"label":title,"description":description})
    return result


def get_default_agent_principles()->Dict[str,List[str]]:
    config=get_agents_config()
    return config.get("agent_principles",{})


def get_output_requirements(agent_type:str)->Dict[str,Any]:
    config=get_agents_config()
    reqs=config.get("output_requirements",{})
    return reqs.get(agent_type,reqs.get("_default",{"min_length":200}))


def get_summary_directive()->str:
    config=get_agents_config()
    settings=config.get("context_policy_settings",{})
    return settings.get("summary_directive","")


def get_agent_usage_category(agent_type:str)->str:
    config=get_agents_config()
    agents=config.get("agents",{})
    agent=agents.get(agent_type,{})
    return agent.get("usage_category","llm_mid")


def get_provider_max_concurrent(provider_id:str)->int:
    provider=get_provider_config(provider_id)
    return provider.get("max_concurrent",3)


def get_provider_group(provider_id:str)->Optional[str]:
    provider=get_provider_config(provider_id)
    return provider.get("group")


def get_group_max_concurrent(group_id:str)->int:
    config=get_ai_providers_config()
    groups=config.get("provider_groups",{})
    group=groups.get(group_id,{})
    return group.get("max_concurrent",5)


def get_mock_content(agent_type:str)->str:
    config=get_mock_data_config()
    mock_contents=config.get("mock_contents",{})
    content=mock_contents.get(agent_type)
    if content is None:
        default_content=mock_contents.get("default","# {agent_type}\n\nモックによる自動生成出力。")
        return default_content.replace("{agent_type}",agent_type)
    return content


def get_checkpoint_title_config(agent_type:str)->Dict[str,str]:
    config=get_mock_data_config()
    titles=config.get("checkpoint_titles",{})
    return titles.get(agent_type,titles.get("default",{"type":"review","title":"レビュー依頼"}))


def get_checkpoint_content(checkpoint_type:str)->str:
    config=get_mock_data_config()
    contents=config.get("checkpoint_contents",{})
    content=contents.get(checkpoint_type)
    if content is None:
        default_content=contents.get("default","# {checkpoint_type}\n\n内容を確認してください。")
        return default_content.replace("{checkpoint_type}",checkpoint_type)
    return content


def get_api_runner_checkpoint_config(agent_type:str)->Dict[str,str]:
    config=get_mock_data_config()
    configs=config.get("api_runner_checkpoint_config",{})
    return configs.get(agent_type,configs.get("default",{"type":"review","title":"レビュー依頼"}))


def get_generation_type_for_agent(agent_type:str)->str:
    config=get_agents_config()
    gen_types=config.get("agent_generation_types",{})
    for gen_type,agents in gen_types.items():
        if agent_type in agents:
            return gen_type
    return"llm"


def get_agent_assets(agent_type:str)->List[Dict[str,Any]]:
    config=get_agents_config()
    assets=config.get("agent_assets",{})
    return assets.get(agent_type,[])


def get_agent_checkpoints(agent_type:str)->List[Dict[str,Any]]:
    config=get_agents_config()
    checkpoints=config.get("agent_checkpoints",{})
    return checkpoints.get(agent_type,[])


def get_provider_config(provider_id:str)->Dict[str,Any]:
    config=get_ai_providers_config()
    providers=config.get("providers",{})
    return providers.get(provider_id,{})


def get_provider_env_key(provider_id:str)->str:
    provider=get_provider_config(provider_id)
    return provider.get("env_key","")


def get_provider_models(provider_id:str)->List[Dict[str,Any]]:
    provider=get_provider_config(provider_id)
    return provider.get("models",[])


def get_provider_test_model(provider_id:str)->str:
    provider=get_provider_config(provider_id)
    test_model=provider.get("test_model")
    if test_model:
        return test_model
    models=provider.get("models",[])
    if models:
        return models[0].get("id","")
    return""


def get_provider_default_model(provider_id:str)->str:
    config=get_ai_providers_config()
    for cat in config.get("usage_categories",[]):
        default=cat.get("default",{})
        if default.get("provider")==provider_id:
            return default.get("model","")
    provider=get_provider_config(provider_id)
    models=provider.get("models",[])
    if models:
        recommended=[m for m in models if m.get("recommended")]
        if recommended:
            return recommended[0].get("id","")
        return models[0].get("id","")
    return""


def get_skills_config()->Dict[str,Any]:
    return load_yaml_config("skills.yaml")


def get_skill_definitions()->Dict[str,Dict[str,Any]]:
    config=get_skills_config()
    return config.get("skills",{})


def get_agent_skill_mapping()->Dict[str,List[str]]:
    config=get_skills_config()
    return config.get("agent_skill_mapping",{})


def get_skills_for_agent(agent_type:str)->List[str]:
    mapping=get_agent_skill_mapping()
    return mapping.get(agent_type,mapping.get("default",[]))


def get_sandbox_config()->Dict[str,Any]:
    config=get_skills_config()
    return config.get("sandbox",{
        "enabled":True,
        "working_dir_base":"/tmp/toybox/projects",
        "timeout_seconds":120,
        "max_output_size":100000,
    })


def get_mock_handlers_config()->Dict[str,Dict[str,Any]]:
    config=get_skills_config()
    return config.get("mock_handlers",{})


def get_mock_handler_config(skill_name:str)->Optional[Dict[str,Any]]:
    handlers=get_mock_handlers_config()
    return handlers.get(skill_name)


def get_generation_metrics_config()->Dict[str,Any]:
    config=get_agents_config()
    return config.get("generation_metrics",{})


def get_generation_metrics_categories()->Dict[str,Dict[str,str]]:
    metrics=get_generation_metrics_config()
    return metrics.get("categories",{})


def get_agent_generation_metrics(agent_type:str)->Optional[Dict[str,Any]]:
    metrics=get_generation_metrics_config()
    agent_metrics=metrics.get("agent_metrics",{})
    return agent_metrics.get(agent_type)
