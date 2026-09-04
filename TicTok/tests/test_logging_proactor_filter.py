import logging

import pytest

from tictok.core.logging_setup import ProactorResetFilter

MESSAGE = (
    "Exception in callback _ProactorBasePipeTransport._call_connection_lost(None)\n"
    "handle: <Handle _ProactorBasePipeTransport._call_connection_lost(None)>"
)


def _record(exc, message=MESSAGE, name="asyncio"):
    record = logging.LogRecord(
        name, logging.ERROR, "proactor_events.py", 165, message, (), (type(exc), exc, None)
    )
    return record


def _peer_gone(winerror=10054):
    return OSError(0, "peer reset", None, winerror)


def test_teardown_reset_is_demoted_to_debug():
    record = _record(_peer_gone())
    assert ProactorResetFilter().filter(record) is True
    assert record.levelno == logging.DEBUG
    assert record.levelname == "DEBUG"


@pytest.mark.parametrize("winerror", [10053, 10058])
def test_other_peer_gone_codes_are_demoted(winerror):
    record = _record(_peer_gone(winerror))
    ProactorResetFilter().filter(record)
    assert record.levelno == logging.DEBUG


def test_reset_masking_a_connection_lost_error_stays_at_error():
    """The shutdown sits in a finally block, so a chained context means a real
    failure from connection_lost is underneath and must not be hidden."""
    exc = _peer_gone()
    exc.__context__ = ValueError("protocol blew up")
    record = _record(exc)
    ProactorResetFilter().filter(record)
    assert record.levelno == logging.ERROR


def test_reset_from_another_callback_stays_at_error():
    record = _record(_peer_gone(), message="Exception in callback Server._start_serving()")
    ProactorResetFilter().filter(record)
    assert record.levelno == logging.ERROR


def test_unrelated_oserror_stays_at_error():
    record = _record(OSError(28, "No space left on device"))
    ProactorResetFilter().filter(record)
    assert record.levelno == logging.ERROR


def test_record_without_exception_stays_at_error():
    record = logging.LogRecord(
        "asyncio", logging.ERROR, "x.py", 1, MESSAGE, (), None
    )
    ProactorResetFilter().filter(record)
    assert record.levelno == logging.ERROR
