"""
設定ファイルローダー
JSON/YAML設定ファイルを読み込み、アプリケーション全体で使用可能にする
"""
import json
import os
from typing import Dict,Any,Optional,Set,List
from pathlib import Path
import yaml


_config_cache:Dict[str,Any] = {}
_config_dir:Optional[Path] = None


def get_config_dir()->Path:
    global _config_dir
    if _config_dir is None:
        _config_dir = Path(__file__).parent / "config"
    return _config_dir


def load_json_config(filename:str,use_cache:bool = True)->Dict[str,Any]:
    global _config_cache

    if use_cache and filename in _config_cache:
        return _config_cache[filename]

    config_path = get_config_dir() / filename
    if not config_path.exists():
        raise FileNotFoundError(f"Config file not found: {config_path}")

    with open(config_path,"r",encoding="utf-8") as f:
        data = json.load(f)

    if use_cache:
        _config_cache[filename] = data

    return data


def load_yaml_config(filename:str,use_cache:bool = True)->Dict[str,Any]:
    global _config_cache

    if use_cache and filename in _config_cache:
        return _config_cache[filename]

    config_path = get_config_dir() / filename
    if not config_path.exists():
        raise FileNotFoundError(f"Config file not found: {config_path}")

    with open(config_path,"r",encoding="utf-8") as f:
        data = yaml.safe_load(f)

    if use_cache:
        _config_cache[filename] = data

    return data or {}


def reload_config(filename:Optional[str] = None):
    """設定キャッシュをクリアして再読み込み"""
    global _config_cache
    if filename:
        _config_cache.pop(filename,None)
    else:
        _config_cache.clear()




def get_models_config()->Dict[str,Any]:
    """モデル設定を取得（非推奨: ai_providers.yamlを使用してください）"""
    try:
        return load_json_config("models.json")
    except FileNotFoundError:
        return {"providers":{},"tokenPricing":{},"defaults":{"temperature":0.7,"maxTokens":4096},"currency":"USD"}


def get_token_pricing(model_id:str)->Dict[str,float]:
    """特定モデルのトークン料金を取得"""
    config = get_models_config()
    pricing = config.get("tokenPricing",{})
    return pricing.get(model_id,pricing.get("_default",{"input":0.003,"output":0.015}))


def get_available_models(provider:str)->List[Dict[str,Any]]:
    """指定プロバイダの利用可能モデル一覧を取得"""
    config = get_models_config()
    provider_config = config.get("providers",{}).get(provider,{})
    return provider_config.get("models",[])


def get_default_model_settings()->Dict[str,Any]:
    """デフォルトのモデル設定を取得"""
    config = get_models_config()
    return config.get("defaults",{"temperature":0.7,"maxTokens":4096})




def get_project_options_config()->Dict[str,Any]:
    """プロジェクトオプション設定を取得"""
    return load_json_config("project_options.json")


def get_platforms()->List[Dict[str,str]]:
    """プラットフォーム選択肢を取得"""
    config = get_project_options_config()
    return config.get("platforms",[])


def get_scopes()->List[Dict[str,str]]:
    """スコープ選択肢を取得"""
    config = get_project_options_config()
    return config.get("scopes",[])


def get_llm_providers()->List[Dict[str,Any]]:
    """LLMプロバイダー選択肢を取得"""
    config = get_project_options_config()
    return config.get("llmProviders",[])


def get_project_defaults()->Dict[str,str]:
    """プロジェクトのデフォルト値を取得"""
    config = get_project_options_config()
    return config.get("defaults",{})




def get_file_extensions_config()->Dict[str,Any]:
    """ファイル拡張子設定を取得"""
    return load_json_config("file_extensions.json")


def get_extensions_for_category(category:str)->Set[str]:
    """カテゴリに属する拡張子のセットを取得"""
    config = get_file_extensions_config()
    categories = config.get("categories",{})
    category_config = categories.get(category,{})
    return set(category_config.get("extensions",[]))


def get_all_extension_categories()->Dict[str,Set[str]]:
    """全カテゴリの拡張子マップを取得"""
    config = get_file_extensions_config()
    categories = config.get("categories",{})
    return {
        cat:set(data.get("extensions",[]))
        for cat,data in categories.items()
    }


def get_scan_directories()->List[str]:
    """スキャン対象ディレクトリ一覧を取得"""
    config = get_file_extensions_config()
    return config.get("scanDirectories",["image","mp3","movie"])




def get_agent_definitions_config()->Dict[str,Any]:
    """エージェント定義設定を取得"""
    return load_json_config("agent_definitions.json")


def get_agent_definitions()->Dict[str,Dict[str,Any]]:
    """エージェント定義を取得"""
    config = get_agent_definitions_config()
    return config.get("agents",{})


def get_high_cost_agents()->Set[str]:
    """高コストエージェントのセットを取得"""
    config = get_agent_definitions_config()
    return set(config.get("highCostAgents",[]))


def get_agent_phases()->Dict[str,List[str]]:
    """エージェントフェーズ定義を取得"""
    config = get_agent_definitions_config()
    return config.get("phases",{})


def get_agent_display_names()->Dict[str,str]:
    """エージェント表示名を取得"""
    config = get_agent_definitions_config()
    return config.get("displayNames",{})


def get_quality_check_defaults()->Dict[str,Any]:
    config = get_agent_definitions_config()
    return config.get("qualityCheckDefaults",{"enabled":True,"maxRetries":3})


def get_project_settings_config()->Dict[str,Any]:
    return load_yaml_config("project_settings.yaml")


def get_output_settings_defaults()->Dict[str,Any]:
    config = get_project_settings_config()
    return config.get("output",{"default_dir":"./output"})


def get_cost_settings_defaults()->Dict[str,Any]:
    config = get_project_settings_config()
    return config.get("cost",{
        "global_enabled":True,
        "global_monthly_limit":100.0,
        "alert_threshold":80,
        "stop_on_budget_exceeded":False,
        "services":{}
    })


def get_agent_service_map()->Dict[str,str]:
    config = get_project_settings_config()
    return config.get("agent_service_map",{})


def get_ai_providers_config()->Dict[str,Any]:
    return load_yaml_config("ai_providers.yaml")


def get_pricing_config()->Dict[str,Any]:
    config = get_ai_providers_config()
    currency = config.get("pricing",{}).get("currency","USD")
    units = config.get("pricing",{}).get("units",{})
    models = {}
    for provider_id,provider in config.get("providers",{}).items():
        for model in provider.get("models",[]):
            models[model["id"]] = {
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


def get_agent_types()->List[str]:
    return list(get_agents_config().get("agents",{}).keys())


def get_workflow_dependencies()->Dict[str,List[str]]:
    return get_agents_config().get("workflow_dependencies",{})


def get_checkpoint_category_map()->Dict[str,str]:
    return get_checkpoints_config().get("category_map",{})


def get_auto_approval_rules()->List[Dict[str,Any]]:
    return get_checkpoints_config().get("auto_approval_rules",[])


def get_status_labels()->Dict[str,str]:
    return get_checkpoints_config().get("status_labels",{})


def get_resolution_labels()->Dict[str,str]:
    return get_checkpoints_config().get("resolution_labels",{})


def get_initial_task(agent_type:str)->str:
    config = get_messages_config()
    tasks = config.get("initial_tasks",{})
    return tasks.get(agent_type,tasks.get("default","[1/3] 初期化: 処理中..."))


def get_task_for_progress(agent_type:str,progress:int)->str:
    config = get_messages_config()
    progress_tasks = config.get("progress_tasks",{})
    agent_tasks = progress_tasks.get(agent_type,[])
    if not agent_tasks:
        return get_initial_task(agent_type)
    current_task = agent_tasks[0].get("task","")
    for item in agent_tasks:
        if progress >= item.get("progress",0):
            current_task = item.get("task","")
    return current_task


def get_milestones(agent_type:str)->List[tuple]:
    config = get_messages_config()
    milestones = config.get("milestones",{})
    agent_milestones = milestones.get(agent_type,[])
    return [(m.get("progress",0),m.get("level","info"),m.get("message","")) for m in agent_milestones]


def get_agent_definitions_from_yaml()->Dict[str,Dict[str,Any]]:
    config = get_agents_config()
    agents = config.get("agents",{})
    result = {}
    for agent_id,agent in agents.items():
        result[agent_id] = {
            "label":agent.get("label",""),
            "shortLabel":agent.get("short_label",""),
            "phase":agent.get("phase",0),
            "speechBubble":agent.get("speech_bubble",""),
        }
    return result


def get_high_cost_agents_from_yaml()->Set[str]:
    config = get_agents_config()
    agents = config.get("agents",{})
    return {k for k,v in agents.items() if v.get("high_cost",False)}


def get_quality_check_defaults_from_yaml()->Dict[str,bool]:
    config = get_agents_config()
    agents = config.get("agents",{})
    return {k:v.get("quality_check",True) for k,v in agents.items()}


def get_agent_phases_from_yaml()->Dict[str,List[str]]:
    config = get_agents_config()
    phases = config.get("phases",{})
    result = {}
    for phase_id,phase in phases.items():
        result[phase_id] = phase.get("agents",[])
    return result


def get_agent_display_names_from_yaml()->Dict[str,str]:
    config = get_agents_config()
    agents = config.get("agents",{})
    return {k:v.get("label","") for k,v in agents.items()}
