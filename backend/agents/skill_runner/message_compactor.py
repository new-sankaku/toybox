"""
Message Compactor Module

会話履歴の圧縮を担当
"""

from typing import Dict,List

from middleware.logger import get_logger


class MessageCompactor:
    def __init__(
        self,
        message_window_size:int=6,
        compact_assistant_max:int=300,
        compact_system_max:int=200,
        compact_user_max:int=200,
    ):
        self._message_window_size=message_window_size
        self._compact_assistant_max=compact_assistant_max
        self._compact_system_max=compact_system_max
        self._compact_user_max=compact_user_max

    def compact_messages(self,messages:List[Dict])->List[Dict]:
        if len(messages)<=self._message_window_size:
            return messages
        first_msg=messages[0]
        keep_count=self._message_window_size
        old_messages=messages[1:-keep_count]
        recent_messages=messages[-keep_count:]
        if not old_messages:
            return messages
        compacted_summary=self._generate_compaction_summary(old_messages)
        summary_msg={
            "role":"user",
            "content":f"[過去の会話要約]\n{compacted_summary}",
        }
        return [first_msg,summary_msg]+recent_messages

    def _generate_compaction_summary(self,old_messages:List[Dict])->str:
        from config_loaders.workflow_config import get_context_policy_settings

        settings=get_context_policy_settings()
        llm_cfg=settings.get("llm_summary",{})
        if not llm_cfg.get("enabled",False):
            return self._fallback_compact(old_messages)
        try:
            from services.summary_service import get_summary_service

            conversation_text=self._serialize_messages_for_summary(old_messages)
            return get_summary_service().generate_summary(
                conversation_text,
                "skill_compaction",
                fallback_func=lambda c:self._fallback_compact(old_messages),
                focus="実行したスキル名と結果、判明した事実、未解決の問題、次に行うべきアクション",
            )
        except Exception as e:
            get_logger().error(
                f"SkillRunner: LLM compaction failed, using fallback: {e}",
                exc_info=True,
            )
            return self._fallback_compact(old_messages)

    def _serialize_messages_for_summary(self,messages:List[Dict])->str:
        parts=[]
        for m in messages:
            role=m["role"]
            content=m["content"]
            if role=="assistant":
                parts.append(f"[assistant] {content[:2000]}")
            elif role=="user":
                parts.append(f"[user] {content[:2000]}")
        return"\n---\n".join(parts)

    def _fallback_compact(self,old_messages:List[Dict])->str:
        summary_parts=[]
        for m in old_messages:
            role=m["role"]
            content=m["content"]
            if role=="assistant":
                has_tool="```tool_call" in content
                text=content[:self._compact_assistant_max]
                if has_tool:
                    summary_parts.append(
                        f"[assistant] ツール呼び出しを実行 (要約: {text}...)"
                    )
                else:
                    summary_parts.append(f"[assistant] {text}...")
            elif role=="user":
                if content.startswith("[ツール実行結果:"):
                    lines=content.split("\n")
                    header=lines[0] if lines else content[:self._compact_system_max]
                    summary_parts.append(f"[tool_result] {header}")
                elif content.startswith("[システム通知]"):
                    summary_parts.append(
                        f"[system] {content[:self._compact_system_max]}"
                    )
                else:
                    summary_parts.append(f"[user] {content[:self._compact_user_max]}...")
        return"\n".join(summary_parts)
