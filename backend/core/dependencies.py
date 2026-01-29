from typing import Optional
from functools import lru_cache

_data_store:Optional["DataStore"]=None
_socket_manager:Optional["SocketManager"]=None


def set_data_store(ds):
 global _data_store
 _data_store=ds


def set_socket_manager(sm):
 global _socket_manager
 _socket_manager=sm


def get_data_store()->"DataStore":
 if _data_store is None:
  raise RuntimeError("DataStore not initialized")
 return _data_store


def get_socket_manager()->"SocketManager":
 if _socket_manager is None:
  raise RuntimeError("SocketManager not initialized")
 return _socket_manager
