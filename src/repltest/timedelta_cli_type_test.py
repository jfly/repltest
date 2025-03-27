import datetime as dt

import pytest
from click import BadParameter

from .timedelta_cli_type import TIMEDELTA


def convert(input: str | dt.timedelta) -> dt.timedelta:
    return TIMEDELTA.convert(value=input, param=None, ctx=None)


def test_noop():
    delta = dt.timedelta(seconds=42)
    assert delta == convert(delta)


def test_ms():
    assert convert("1234ms") == dt.timedelta(milliseconds=1234)


def test_bad_count():
    with pytest.raises(BadParameter) as exc_info:
        convert("!ms")

    assert "'!ms' is not a valid time delta: bad count: '!'" == str(exc_info.value)


def test_bad_unit():
    with pytest.raises(BadParameter) as exc_info:
        convert("42jfly")

    assert "'42jfly' is not a valid time delta: bad unit: 'jfly'" == str(exc_info.value)
