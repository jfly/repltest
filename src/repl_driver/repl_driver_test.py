import datetime as dt

import _pytest.fixtures
import pytest

from .exceptions import ReplTimeoutException
from .repl_driver import ReplDriver

# Not a timeout we expect to hit, just something to make sure if
# something goes wrong the tests stop rather than hang.
TIMEOUT_FOR_TESTS = dt.timedelta(seconds=10)

SIMPLE_REPLS = [
    "test-repl-read-cooked",
    # <<< TODO: test-repl-read-raw >>>
    # <<< "test-repl-readline-async",
]

MULTILINE_REPLS = [
    # <<< TODO >>>
]


@pytest.fixture(params=SIMPLE_REPLS + MULTILINE_REPLS)
def any_repl(request: _pytest.fixtures.SubRequest):
    return request.param


@pytest.fixture(params=MULTILINE_REPLS)
def multiline_repl(request: _pytest.fixtures.SubRequest):
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
            b">> Bye!\r\n",
        ]

    def test_multiline(self, multiline_repl: str):
        pass  # <<< TODO >>>

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
