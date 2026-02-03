from typing import Optional,Type,Dict,Any,List
from functools import wraps
from pydantic import BaseModel


class ApiEndpointDoc:
    def __init__(
        self,
        endpoint:str,
        method:str,
        handler_name:str,
        handler_file:str,
        request_schema:Optional[Type[BaseModel]],
        response_schema:Optional[Type[BaseModel]],
        response_list:bool,
        query_params:Optional[Dict[str,type]],
        emits:Optional[List[str]],
        description:str,
    ):
        self.endpoint=endpoint
        self.method=method
        self.handler_name=handler_name
        self.handler_file=handler_file
        self.request_schema=request_schema
        self.response_schema=response_schema
        self.response_list=response_list
        self.query_params=query_params or {}
        self.emits=emits or []
        self.description=description


_api_registry:List[ApiEndpointDoc]=[]


def get_api_registry()->List[ApiEndpointDoc]:
    return _api_registry


def api_doc(
    endpoint:str,
    method:str,
    response:Optional[Type[BaseModel]]=None,
    request:Optional[Type[BaseModel]]=None,
    response_list:bool=False,
    query_params:Optional[Dict[str,type]]=None,
    emits:Optional[List[str]]=None,
    description:str="",
):
    def decorator(func):
        import inspect
        frame=inspect.stack()[1]
        handler_file=frame.filename

        doc=ApiEndpointDoc(
            endpoint=endpoint,
            method=method,
            handler_name=func.__name__,
            handler_file=handler_file,
            request_schema=request,
            response_schema=response,
            response_list=response_list,
            query_params=query_params,
            emits=emits,
            description=description,
        )
        _api_registry.append(doc)

        @wraps(func)
        def wrapper(*args,**kwargs):
            return func(*args,**kwargs)
        wrapper._api_doc=doc
        return wrapper
    return decorator
