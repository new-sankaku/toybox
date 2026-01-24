"""
設定ファイルローダー
JSON設定ファイルを読み込み、アプリケーション全体で使用可能にする
"""
import json
import os
from typing import Dict,Any,Optional,Set,List
from pathlib import Path


_config_cache:Dict[str,Any] = {}
_config_dir:Optional[Path] = None


def get_config_dir()->Path:
    """設定ファイルディレクトリのパスを取得"""
    global _config_dir
    if _config_dir is None:
        _config_dir = Path(__file__).parent / "config"
    return _config_dir


def load_json_config(filename:str,use_cache:bool = True)->Dict[str,Any]:
    """JSON設定ファイルを読み込む"""
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


def reload_config(filename:Optional[str] = None):
    """設定キャッシュをクリアして再読み込み"""
    global _config_cache
    if filename:
        _config_cache.pop(filename,None)
    else:
        _config_cache.clear()




def get_models_config()->Dict[str,Any]:
    """モデル設定を取得"""
    return load_json_config("models.json")


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
    """品質チェックのデフォルト設定を取得"""
    config = get_agent_definitions_config()
    return config.get("qualityCheckDefaults",{"enabled":True,"maxRetries":3})
