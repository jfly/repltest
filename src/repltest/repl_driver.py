import datetime as dt
import logging
import os
import termios
import time
from dataclasses import dataclass
from typing import Any, Callable

import pyte

from .exceptions import ReplProcessException, ReplTimeoutException
from .spawn import Child, RunningChild
from .util import get_special_char_vals

logger = logging.getLogger(__name__)

__all__ = [
    "ReplDriver",
]


def is_echo_enabled(tty: int) -> bool:
    _iflag, _oflag, _cflag, lflag, _ispeed, _ospeed, _cc = termios.tcgetattr(tty)
    return lflag & termios.ECHO != 0


class GrowingScreen(pyte.Screen):
    """
    A `pyte.Screen` that grows vertically to accomodate output.
    """

    def index(self) -> None:
        top, bottom = self.margins or pyte.screens.Margins(0, self.lines - 1)

        if self.cursor.y == bottom:
            self.resize(
                lines=self.lines + 1,
                columns=self.columns,
            )

        super().index()

    def reverse_index(self) -> None:
        assert False, "Not supported"  # pragma: no cover


@dataclass
class DriveReplResult:
    screen: GrowingScreen
    entrypoint_exit_code: int


class ReplDriver:
    def __init__(
        self,
        entrypoint: list[str],
        columns: int,
        lines: int,
        timeout: dt.timedelta | None,
        cleanup_term_after: dt.timedelta | None,
        cleanup_kill_after: dt.timedelta | None,
        input_callback: Callable[[pyte.Screen, str], bytes | None],
        on_output: Callable[[pyte.Screen, bytes], Any],
        env: dict[str, str] | None = None,
        check_nonzero_exit_code: bool = True,
    ):
        self.screen = GrowingScreen(columns, lines)
        self.exit_code = None

        self._entrypoint = entrypoint
        self._env = env
        self._input_callback = input_callback
        self._on_output = on_output
        self._timeout = timeout
        self._cleanup_term_after = cleanup_term_after
        self._cleanup_kill_after = cleanup_kill_after
        self._check_nonzero_exit_code = check_nonzero_exit_code
        self._started = False
        self._done = False

        self._stream = pyte.ByteStream(self.screen)
        self._last_prompt_y = None

    def drive(self):
        assert not self._started, "Cannot start a driver which has already been started"
        self._started = True

        timeout = self._timeout

        child = Child(
            self._entrypoint,
            cleanup_term_after=self._cleanup_term_after,
            cleanup_kill_after=self._cleanup_kill_after,
            env=self._env,
        )
        try:
            with child.spawn() as running_child:
                assert not self._done
                start_ts = time.monotonic()
                while not self._done:
                    if timeout is not None:
                        elapsed_seconds = dt.timedelta(
                            seconds=time.monotonic() - start_ts
                        )
                        budget = timeout - elapsed_seconds
                    else:
                        budget = None

                    running_child.wait_for_events(
                        timeout=budget,
                        on_output=self._handle_output,
                        on_subsidiary_closed=self._handle_subsidiary_closed,
                    )

                    if timeout is not None:
                        elapsed_seconds = time.monotonic() - start_ts
                        if elapsed_seconds > timeout.total_seconds():
                            raise ReplTimeoutException()
        finally:
            assert child.exit_code is not None
            self.exit_code = child.exit_code

        assert self.exit_code is not None
        if self._check_nonzero_exit_code and self.exit_code != 0:
            raise ReplProcessException(self._entrypoint, self.exit_code)

    def _handle_subsidiary_closed(self, running_child: RunningChild):
        """
        Called when the subsidiary side of the TTY is closed.
        AKA: when no more processes have it open, which means
        there's no reason to keep running.
        """
        logger.debug("Subsidiary TTY is closed")
        self._done = True

    def _get_current_prompt(self) -> str | None:
        cursor = self.screen.cursor

        # Don't rediscover the previous prompt. For example, if the previous prompt
        # was "$ " and we're partway through a command: "$ ls", we don't
        # want to mistake that for a new prompt.
        if cursor.y == self._last_prompt_y:
            return None  # pragma: no cover # Our tests don't reliably hit this line :(.

        # A prompt must have some characters.
        if cursor.x == 0:
            return None

        prompt = "".join(self.screen.buffer[cursor.y][x].data for x in range(cursor.x))
        return prompt

    def _handle_output(self, running_child: RunningChild, output: bytes):
        """
        Called when a child process has written some output to the PTY.
        """
        logger.debug("Just read %s", output)
        self._stream.feed(output)
        self._on_output(self.screen, output)

        possible_prompt = self._get_current_prompt()
        if possible_prompt is not None:
            if not is_echo_enabled(running_child.manager_fd):
                self._handle_prompt(running_child, possible_prompt)

    def _handle_prompt(self, running_child: RunningChild, prompt: str):
        logger.debug("Child is prompting: %r", prompt)

        to_write = self._input_callback(self.screen, prompt)

        if to_write is None:
            # This will cause us to exit the loop in `self.drive` and tear down the
            # PTY. This will result in the kernel sending SIGHUP to the child process.
            self._done = True
            return

        assert len(to_write) > 0, "Input must be longer than 0 bytes"

        manager_fd = running_child.manager_fd
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
        self._last_prompt_y = self.screen.cursor.y
