import datetime as dt
import shlex
from pprint import pprint

import _pytest.fixtures
import pyte
import pytest

from .exceptions import ReplProcessException, ReplTimeoutException
from .repl_driver import ReplDriver

REPEAT_REPLS = [
    "test-repl-readline-async poll",
    "test-repl-readline-async select",
]


@pytest.fixture(params=REPEAT_REPLS)
def repeat_repl(request: _pytest.fixtures.SubRequest):
    return shlex.split(request.param)


class TestDriveRepl:
    def _drive(
        self,
        entrypoint: list[str],
        inputs: list[str],
        # Not a timeout we expect to hit, just something to
        # ensure that the tests don't run forever.
        timeout: dt.timedelta = dt.timedelta(seconds=10),
    ):
        events = []

        def input_callback(screen: pyte.Screen, prompt: str):
            input = inputs.pop(0)
            events.append("<< " + input)
            return input.encode()

        def on_output(screen: pyte.Screen, out_b: bytes):
            output = out_b.decode()

            if len(events) > 0 and events[-1].startswith(">> "):
                events[-1] += output
            else:
                events.append(">> " + output)

        repl_driver = ReplDriver(
            entrypoint=entrypoint,
            input_callback=input_callback,
            on_output=on_output,
            columns=80,
            lines=120,
            timeout=timeout,
            # No reason to wait at all for a graceful cleanup in tests.
            # If the process doesn't exit cleanly, proceed immediately to killing it.
            cleanup_term_after=dt.timedelta(seconds=0),
            cleanup_kill_after=dt.timedelta(seconds=0),
        )
        try:
            repl_driver.drive()
        except ReplProcessException:
            print("Looks like the REPL crashed. Here are the events so far:")
            pprint(events)
            raise
        assert len(inputs) == 0

        return events

    def test_oneline_inputs(self, repeat_repl: list[str]):
        events = self._drive(
            entrypoint=repeat_repl,
            inputs=[
                "foo\n",
                "\n",
                "prompt> \n",
                "\x04",  # ASCII "end of transmission"
            ],
        )

        assert events == [
            ">> This is a nice\r\n... long\r\nmultiline intro.\r\nprompt> ",
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
                entrypoint=["bash"],
                inputs=[
                    "sleep 5\n",
                ],
                timeout=dt.timedelta(milliseconds=100),
            )

    def test_read_with_echo(self):
        # We don't support processes that read from stdin with ECHO enabled.
        with pytest.raises(ReplTimeoutException):
            self._drive(
                entrypoint=["test-repl-read-cooked"],
                inputs=[],
                timeout=dt.timedelta(milliseconds=100),
            )

    def test_crash(self):
        with pytest.raises(ReplProcessException) as exc_info:
            self._drive(
                entrypoint=["bash"],
                inputs=[
                    "exit 42\n",
                ],
            )

        assert 42 == exc_info.value.exit_code
        assert "Command: 'bash' exited with exit code: 42" == str(exc_info.value)

    def test_sh(self):
        events = self._drive(
            entrypoint=["sh"],
            inputs=[
                "echo hiya\n",
                "exit\n",
            ],
        )

        assert events == [
            ">> \x1b[?2004hsh-5.2$ ",
            "<< echo hiya\n",
            ">> echo hiya\r\n\x1b[?2004l\rhiya\r\n\x1b[?2004hsh-5.2$ ",
            "<< exit\n",
            ">> exit\r\n\x1b[?2004l\rexit\r\n",
        ]
