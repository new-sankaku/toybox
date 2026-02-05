"""
Output Processor Module

出力整形・チェックポイント生成を担当
"""

from datetime import datetime
from typing import Any,Dict,TYPE_CHECKING

from config_loaders.mock_config import get_api_runner_checkpoint_config

if TYPE_CHECKING:
    from ..base import AgentContext


class OutputProcessor:
    def process_output(
        self,result:Dict[str,Any],context:"AgentContext"
    )->Dict[str,Any]:
        return {
            "type":"document",
            "format":"markdown",
            "content":result.get("content",""),
            "metadata":{
                "model":result.get("model"),
                "tokens_used":result.get("tokens_used"),
                "agent_type":context.agent_type.value,
            },
        }

    def generate_checkpoint(
        self,context:"AgentContext",output:Dict[str,Any]
    )->Dict[str,Any]:
        agent_type=(
            context.agent_type.value
            if hasattr(context.agent_type,"value")
            else str(context.agent_type)
        )
        cp_config=get_api_runner_checkpoint_config(agent_type)
        cp_type=cp_config.get("type","review")
        title=cp_config.get("title","レビュー依頼")
        return {
            "type":cp_type,
            "title":title,
            "description":f"{agent_type}エージェントの出力を確認してください",
            "output":output,
            "timestamp":datetime.now().isoformat(),
        }
