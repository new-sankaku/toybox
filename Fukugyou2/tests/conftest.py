import os
import socket
import sys

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "tools"))


@pytest.fixture(autouse=True)
def no_network(monkeypatch):
    """test から外部へ出ないようにします。出ようとしたら、その場で落とします。"""
    def blocked(*a, **kw):
        raise RuntimeError("test から network に出ようとしました。stub にしてください。")
    monkeypatch.setattr(socket, "socket", blocked)
    monkeypatch.setattr(socket, "create_connection", blocked)
