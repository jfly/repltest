import datetime as dt
import logging
import os
import termios
import time
from typing import Any, Callable

import pyte

from .exceptions import ReplTimeoutException
from .spawn import Child, spawn_child_in_tty
from .util import get_special_char_vals

logger = logging.getLogger(__name__)

__all__ = [
    "drive_repl",
]


def is_echo_enabled(tty: int) -> bool:
    _iflag, _oflag, _cflag, lflag, _ispeed, _ospeed, _cc = termios.tcgetattr(tty)
    return lflag & termios.ECHO != 0


def drive_repl(
    args: list[str],
    input_callback: Callable[[], bytes],
    on_output: Callable[[bytes], Any],
    timeout: dt.timedelta | None = None,
    cleanup_kill_after: dt.timedelta = dt.timedelta(seconds=5),
    env: dict[str, str] | None = None,
):
    with spawn_child_in_tty(
        args,
        cleanup_kill_after=cleanup_kill_after,
        env=env,
    ) as child:
        DriveRepl(
            child=child,
            input_callback=input_callback,
            on_output=on_output,
            timeout=timeout,
        )


class DriveRepl:
    """This is an implementation detail. The public API is `drive_repl`."""

    def __init__(
        self,
        child: Child,
        input_callback: Callable[[], bytes],
        on_output: Callable[[bytes], Any],
        timeout: dt.timedelta | None = None,
        columns: int = 80,
        lines: int = 24,
    ):
        self._child = child
        self._input_callback = input_callback
        self._on_output = on_output
        self._screen = pyte.Screen(columns, lines)
        self._stream = pyte.ByteStream(self._screen)
        self._last_prompt_y = None
        self._done = False

        start_ts = time.monotonic()
        while not self._done:
            if timeout is not None:
                elapsed_seconds = dt.timedelta(seconds=time.monotonic() - start_ts)
                budget = timeout - elapsed_seconds
            else:  # pragma: no cover # we always have a timeout in tests
                budget = None

            child.wait_for_events(
                timeout=budget,
                on_output=self._handle_output,
                on_subsidiary_closed=self._handle_subsidiary_closed,
            )

            if timeout is not None:
                elapsed_seconds = time.monotonic() - start_ts
                if elapsed_seconds > timeout.total_seconds():
                    raise ReplTimeoutException()

    def _handle_subsidiary_closed(self):
        """
        Called when the subsidiary side of the TTY is closed.
        AKA: when no more processes have it open, which means
        there's no reason to keep running.
        """
        logger.debug("Subsidiary TTY is closed")
        self._done = True

    def _get_current_prompt(self) -> str | None:
        cursor = self._screen.cursor

        # Don't rediscover the previous prompt. For example, if the previous prompt
        # was "$ " and we're partway through a command: "$ ls", we don't
        # want to mistake that for a new prompt.
        if cursor.y == self._last_prompt_y:
            return None

        # A prompt must have some characters.
        if cursor.x == 0:
            return None

        prompt = "".join(self._screen.buffer[cursor.y][x].data for x in range(cursor.x))
        return prompt

    def _handle_output(self, output: bytes):
        """
        Called when a child process has written some output to the PTY.
        """
        logger.debug("Just read %s", output)
        self._stream.feed(output)
        self._on_output(output)

        possible_prompt = self._get_current_prompt()
        if possible_prompt is not None:
            if not is_echo_enabled(self._child.manager_fd):
                self._handle_prompt(possible_prompt)

    def _handle_prompt(self, prompt: str):
        logger.debug("Child is prompting: %r", prompt)

        to_write = self._input_callback()
        assert len(to_write) > 0, "Input must be longer than 0 bytes"

        manager_fd = self._child.manager_fd
        special_char_vals = get_special_char_vals(manager_fd)
        has_special_chars = len(special_char_vals & set(to_write)) > 0
        if has_special_chars:
            assert len(to_write) == 1, (
                "We currently only support sending exactly 1 special character at a time"
            )
        else:
            assert not has_special_chars
            assert to_write.endswith(b"\n"), (
                "Input without special chars must end in a newline"
            )

        os.write(manager_fd, to_write)
        logger.debug("Just wrote %s", to_write)
        self._last_prompt_y = self._screen.cursor.y
