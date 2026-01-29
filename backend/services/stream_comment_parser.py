from typing import Optional, Callable
from config_loader import load_yaml_config
from middleware.logger import get_logger


class StreamCommentParser:
    def __init__(self, on_comment: Optional[Callable[[str], None]] = None):
        config = load_yaml_config("agent_personality.yaml")
        policy = config.get("comment_policy", {})
        self._start = policy.get("delimiter_start", "[COMMENT]")
        self._end = policy.get("delimiter_end", "[/COMMENT]")
        self._buffer_limit = policy.get("buffer_limit", 200)
        self._on_comment = on_comment
        self._buffer = ""
        self._found_start = False
        self._comment_extracted = False
        self._comment: Optional[str] = None

    def feed(self, chunk: str) -> None:
        if self._comment_extracted:
            return
        self._buffer += chunk
        if not self._found_start:
            if self._start in self._buffer:
                self._found_start = True
                idx = self._buffer.index(self._start) + len(self._start)
                self._buffer = self._buffer[idx:]
            elif len(self._buffer) > self._buffer_limit:
                self._comment_extracted = True
                return
        if self._found_start:
            if self._end in self._buffer:
                idx = self._buffer.index(self._end)
                self._comment = self._buffer[:idx].strip()
                self._comment_extracted = True
                if self._on_comment and self._comment:
                    self._on_comment(self._comment)
            elif len(self._buffer) > self._buffer_limit:
                self._comment = self._buffer[: self._buffer_limit].strip()
                self._comment_extracted = True
                if self._on_comment and self._comment:
                    self._on_comment(self._comment)

    @property
    def comment(self) -> Optional[str]:
        return self._comment

    @property
    def done(self) -> bool:
        return self._comment_extracted

    @staticmethod
    def strip_comment(full_text: str) -> str:
        config = load_yaml_config("agent_personality.yaml")
        policy = config.get("comment_policy", {})
        start = policy.get("delimiter_start", "[COMMENT]")
        end = policy.get("delimiter_end", "[/COMMENT]")
        s_idx = full_text.find(start)
        if s_idx == -1:
            return full_text
        e_idx = full_text.find(end, s_idx)
        if e_idx == -1:
            return full_text[:s_idx] + full_text[s_idx + len(start) :]
        return (full_text[:s_idx] + full_text[e_idx + len(end) :]).strip()
