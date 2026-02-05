"""
Skill Runner Types Module

スキルランナーで使用されるデータクラスと定数
"""

from collections import Counter
from dataclasses import dataclass,field
from typing import Any,Dict,List,Optional


DEFAULT_MAX_ITERATIONS=50
LOOP_DETECTION_WINDOW=6
LOOP_DETECTION_REPEAT_THRESHOLD=3
FINALIZING_BUDGET=1
DEFAULT_MESSAGE_WINDOW_SIZE=6
DEFAULT_MESSAGE_COMPACTION_TRIGGER=10


@dataclass
class ToolCall:
    id:str
    name:str
    input:Dict[str,Any]


@dataclass
class IterationRecord:
    iteration:int
    skill_names:List[str]=field(default_factory=list)
    skill_results:List[bool]=field(default_factory=list)


class LoopDetector:
    def __init__(
        self,
        window:int=LOOP_DETECTION_WINDOW,
        repeat_threshold:int=LOOP_DETECTION_REPEAT_THRESHOLD,
    ):
        self._window=window
        self._repeat_threshold=repeat_threshold
        self._history:List[str]=[]

    def record(self,skill_names:List[str]):
        key=",".join(sorted(skill_names))
        self._history.append(key)

    def is_looping(self)->bool:
        if len(self._history)<self._window:
            return False
        recent=self._history[-self._window :]
        counts=Counter(recent)
        most_common_count=counts.most_common(1)[0][1]
        return most_common_count>=self._repeat_threshold

    def get_loop_info(self)->Optional[str]:
        if not self.is_looping():
            return None
        recent=self._history[-self._window :]
        counts=Counter(recent)
        pattern,count=counts.most_common(1)[0]
        return f"直近{self._window}回中{count}回同一パターン: [{pattern}]"
