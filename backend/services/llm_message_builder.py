import json
import re
from typing import Dict,Any,Optional,Callable
from providers.base import ChatMessage,MessageRole,ToolCallData
from services.stream_comment_parser import StreamCommentParser


class LlmMessageBuilder:
    @staticmethod
    def build_messages(job)->list:
        messages=[]
        if job.messages_json:
            raw_msgs=json.loads(job.messages_json)
            if job.system_prompt:
                messages.append(ChatMessage(role=MessageRole.SYSTEM,content=job.system_prompt))
            for m in raw_msgs:
                messages.append(LlmMessageBuilder._convert_message(m))
        else:
            if job.system_prompt:
                messages.append(ChatMessage(role=MessageRole.SYSTEM,content=job.system_prompt))
            messages.append(ChatMessage(role=MessageRole.USER,content=job.prompt))
        return messages

    @staticmethod
    def _convert_message(m:Dict)->ChatMessage:
        role_str=m.get("role","user")
        if role_str=="system":
            return ChatMessage(role=MessageRole.SYSTEM,content=m["content"])
        if role_str=="assistant":
            raw_tc=m.get("tool_calls")
            tc_data=None
            if raw_tc:
                tc_data=[ToolCallData(id=t["id"],name=t["name"],arguments=t["arguments"]) for t in raw_tc]
            return ChatMessage(role=MessageRole.ASSISTANT,content=m.get("content",""),tool_calls=tc_data)
        if role_str=="tool":
            return ChatMessage(role=MessageRole.TOOL,content=m["content"],tool_call_id=m.get("tool_call_id"))
        return ChatMessage(role=MessageRole.USER,content=m["content"])

    @staticmethod
    def build_chat_kwargs(job,messages:list)->Dict[str,Any]:
        chat_kwargs={"messages":messages,"model":job.model,"max_tokens":job.max_tokens}
        if job.temperature:
            chat_kwargs["temperature"]=float(job.temperature)
        if job.tools_json:
            chat_kwargs["tools"]=json.loads(job.tools_json)
        return chat_kwargs

    @staticmethod
    def serialize_tool_calls_response(content:str,tool_calls)->str:
        if not tool_calls:
            return content
        tc_list=[{"id":tc.id,"name":tc.name,"arguments":tc.arguments} for tc in tool_calls]
        return json.dumps({"content":content,"tool_calls":tc_list},ensure_ascii=False)


class LlmStreamExecutor:
    def __init__(self,provider,chat_kwargs:Dict[str,Any]):
        self._provider=provider
        self._chat_kwargs=chat_kwargs

    def execute_stream(self,speech_cb:Optional[Callable[[str],None]]=None)->tuple:
        parser=StreamCommentParser(on_comment=speech_cb) if speech_cb else None
        full_content=""
        input_tokens=0
        output_tokens=0
        collected_tool_calls=None
        for chunk in self._provider.chat_stream(**self._chat_kwargs):
            if chunk.is_final:
                if chunk.input_tokens is not None:
                    input_tokens=chunk.input_tokens
                if chunk.output_tokens is not None:
                    output_tokens=chunk.output_tokens
                if chunk.tool_calls:
                    collected_tool_calls=chunk.tool_calls
            else:
                full_content+=chunk.content
                if parser and not parser.done:
                    parser.feed(chunk.content)
        if parser:
            full_content=StreamCommentParser.strip_comment(full_content)
        return full_content,input_tokens,output_tokens,collected_tool_calls

    def execute_fallback(self,speech_cb:Optional[Callable[[str],None]]=None)->tuple:
        response=self._provider.chat(**self._chat_kwargs)
        fallback_content=response.content
        if speech_cb and fallback_content:
            match=re.search(r'\[COMMENT\](.*?)\[/COMMENT\]',fallback_content,re.DOTALL)
            if match:
                speech_cb(match.group(1).strip())
            fallback_content=StreamCommentParser.strip_comment(fallback_content)
        return fallback_content,response.input_tokens,response.output_tokens,response.tool_calls
