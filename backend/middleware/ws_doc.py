from typing import Optional,Type,Dict,Any,List
from pydantic import BaseModel


class WsEventDoc:
    def __init__(
        self,
        event:str,
        direction:str,
        data_fields:Dict[str,str],
        room:str="",
        description:str="",
    ):
        self.event=event
        self.direction=direction
        self.data_fields=data_fields
        self.room=room
        self.description=description


_ws_registry:List[WsEventDoc]=[]


def get_ws_registry()->List[WsEventDoc]:
    return _ws_registry


def ws_event(
    event:str,
    direction:str,
    data_fields:Dict[str,str],
    room:str="",
    description:str="",
):
    doc=WsEventDoc(
        event=event,
        direction=direction,
        data_fields=data_fields,
        room=room,
        description=description,
    )
    _ws_registry.append(doc)
    return doc
