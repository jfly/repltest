import datetime as dt
from pprint import pprint

import _pytest.fixtures
import pytest

from .drive_repl import drive_repl
from .exceptions import ReplProcessException, ReplTimeoutException

REPLS = [
    ["test-repl-read-cooked"],
    ["test-repl-readline-async", "poll"],
    ["test-repl-readline-async", "select"],
]


@pytest.fixture(params=REPLS)
def any_repl(request: _pytest.fixtures.SubRequest):
    return request.param


class TestDriveRepl:
    def _drive(
        self,
        args: list[str],
        inputs: list[str],
        # Not a timeout we expect to hit, just something to
        # ensure that the tests don't run forever.
        timeout: dt.timedelta = dt.timedelta(seconds=10),
    ):
        events = []

        def input_callback():
            input = inputs.pop(0)
            events.append("<< " + input)
            return input.encode()

        def on_output(out_b: bytes):
            output = out_b.decode()

            if len(events) > 0 and events[-1].startswith(">> "):
                events[-1] += output  # pragma: no cover # doesn't always happen
            else:
                events.append(">> " + output)

        try:
            drive_repl(
                args=args,
                input_callback=input_callback,
                on_output=on_output,
                timeout=timeout,
                # No reason to wait at all for a graceful cleanup in tests.
                # If the process doesn't exit cleanly, proceed immediately to killing it.
                cleanup_kill_after=dt.timedelta(seconds=0),
            )
        except ReplProcessException:
            print("Looks like the REPL crashed. Here are the events so far:")
            pprint(events)
            raise
        assert len(inputs) == 0

        return events

    def test_oneline_inputs(self, any_repl: list[str]):
        events = self._drive(
            args=any_repl,
            inputs=[
                "foo\n",
                "\n",
                "prompt> \n",
                "\x04",  # ASCII "end of transmission"
            ],
        )

        assert events == [
            ">> prompt> ",
            "<< foo\n",
            ">> foo\r\nfoo\r\nprompt> ",
            "<< \n",
            ">> \r\n\r\nprompt> ",
            "<< prompt> \n",
            ">> prompt> \r\nprompt> \r\nprompt> ",
            "<< \x04",
            ">> Bye!\r\n",
        ]

    def test_timeout(self):
        with pytest.raises(ReplTimeoutException):
            self._drive(
                args=["bash"],
                inputs=[
                    "sleep 5\n",
                ],
                timeout=dt.timedelta(milliseconds=100),
            )

    def test_crash(self):
        with pytest.raises(ReplProcessException) as exc_info:
            self._drive(
                args=["bash"],
                inputs=[
                    "exit 42\n",
                ],
            )

        assert 42 == exc_info.value.returncode
        assert "Command: 'bash' exited with returncode: 42" == str(exc_info.value)
