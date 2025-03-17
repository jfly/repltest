import datetime as dt

import _pytest.fixtures
import pytest

from .exceptions import ReplTimeoutException
from .repl_driver import ReplDriver

# Not a timeout we expect to hit, just something to
# ensure that the tests don't run forever.
TIMEOUT_FOR_TESTS = dt.timedelta(seconds=10)

REPLS = [
    "test-repl-read-cooked",
    "test-repl-readline-async",
]


@pytest.fixture(params=REPLS)
def any_repl(request: _pytest.fixtures.SubRequest):
    return request.param


class TestReplDriver:
    def test_oneline_inputs(self, any_repl: str):
        events = []
        inputs = [
            "foo\n",
            "\n",
            "prompt> \n",
            "\x04",  # ASCII "end of transmission"
        ]

        def input_callback():
            input = inputs.pop(0).encode()
            events.append(b"<< " + input)
            return input

        def on_output(output: bytes):
            if len(events) > 0 and events[-1].startswith(b">> "):
                events[-1] += output  # pragma: no cover # doesn't always happen
            else:
                events.append(b">> " + output)

        driver = ReplDriver(
            args=[any_repl],
            input_callback=input_callback,
            on_output=on_output,
            timeout=TIMEOUT_FOR_TESTS,
        )

        driver.check_returncode()
        assert len(inputs) == 0
        assert events == [
            b">> prompt> ",
            b"<< foo\n",
            b">> foo\r\nfoo\r\nprompt> ",
            b"<< \n",
            b">> \r\n\r\nprompt> ",
            b"<< prompt> \n",
            b">> prompt> \r\nprompt> \r\nprompt> ",
            b"<< \x04",
            b">> \r\nBye!\r\n",
        ]

    def test_timeout(self):
        def assert_not_called(*_args, **_kwargs):
            assert False  # pragma: no cover

        with pytest.raises(ReplTimeoutException):
            ReplDriver(
                args=["sleep", "5"],
                input_callback=assert_not_called,
                on_output=assert_not_called,
                timeout=dt.timedelta(milliseconds=100),
            )
