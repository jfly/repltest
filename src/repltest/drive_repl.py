import datetime as dt
import enum
import logging
import os
import time
from typing import Any, Callable, ContextManager

from . import analyze_syscall
from .exceptions import ReplProcessException, ReplTimeoutException
from .instrumented_child import InstrumentedChild, instrumented_child
from .util import get_special_char_vals, graceful_shutdown

logger = logging.getLogger(__name__)

__all__ = [
    "drive_repl",
]


def drive_repl(
    args: list[str],
    input_callback: Callable[[], bytes],
    on_output: Callable[[bytes], Any],
    timeout: dt.timedelta | None = None,
    cleanup_kill_after: dt.timedelta = dt.timedelta(seconds=5),
):
    with instrumented_child(
        args,
        syscalls_to_instrument=analyze_syscall.SYSCALLS_THAT_COULD_INDICATE_WANTS_STDIN,
    ) as child:
        try:
            DriveRepl(
                child=child,
                input_callback=input_callback,
                on_output=on_output,
                timeout=timeout,
            )
        finally:
            returncode = child.returncode
            if returncode is None:
                logger.debug(
                    "Child process %s appears to still be running. Attempting to shut it down.",
                    child.pid,
                )
                returncode = graceful_shutdown(
                    child.pid,
                    term_after=dt.timedelta(seconds=0),
                    kill_after=cleanup_kill_after,
                )

        if returncode != 0:
            raise ReplProcessException(args, returncode)


class State(enum.Enum):
    AWAITING_STDIN_READ = enum.auto()
    SENT_INPUT_AWAITING_CRLF = enum.auto()
    SENT_INPUT_AWAITING_OUTPUT = enum.auto()
    DONE = enum.auto()


class DriveRepl:
    """This is an implementation detail. The public API is `drive_repl`."""

    def __init__(
        self,
        child: InstrumentedChild,
        input_callback: Callable[[], bytes],
        on_output: Callable[[bytes], Any],
        timeout: dt.timedelta | None = None,
    ):
        self._child = child
        self._input_callback = input_callback
        self._on_output = on_output
        self._state = State.AWAITING_STDIN_READ

        start_ts = time.monotonic()
        while self._state != State.DONE:
            if timeout is not None:
                elapsed_seconds = dt.timedelta(seconds=time.monotonic() - start_ts)
                budget = timeout - elapsed_seconds
            else:  # pragma: no cover # we always have a timeout in tests
                budget = None

            child.wait_for_events(
                timeout=budget,
                on_output=self._handle_output,
                on_subsidiary_closed=self._handle_subsidiary_closed,
                on_syscall=self._handle_syscall,
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
        logger.debug("%s: subsidiary TTY is closed", self._state.name)
        self._set_state(State.DONE)

    def _handle_output(self, output: bytes):
        """
        Called when a child process has written some output to the PTY.
        """
        logger.debug("%s: Just read %s", self._state.name, output)
        self._on_output(output)

        if self._state == State.SENT_INPUT_AWAITING_CRLF:
            if output.endswith(b"\r\n"):
                self._set_state(State.SENT_INPUT_AWAITING_OUTPUT)
            elif b"\r\n" in output:
                self._set_state(State.AWAITING_STDIN_READ)
        elif self._state == State.SENT_INPUT_AWAITING_OUTPUT:
            self._set_state(State.AWAITING_STDIN_READ)

    def _handle_syscall(self, with_syscall: ContextManager[analyze_syscall.Syscall]):
        """
        Some child/descendant process has made a syscall we're instrumenting.
        """
        child_wants_stdin = False
        with with_syscall as syscall:
            with self._child.with_subsidiary_fd() as subsidiary_fd:
                child_wants_stdin = syscall.indicates_desire_to_read_fd(subsidiary_fd)
                logger.debug(
                    "%s: syscall %s -> child_wants_stdin=%s",
                    self._state.name,
                    syscall,
                    child_wants_stdin,
                )

                # Make sure we've read everything the child has has already output.
                # This may transition us into `State.AWAITING_STDIN_READ`, which means
                # this syscall is a legitimate sign that we should send more to the child
                # (rather than a sign that the child hasn't read everything we sent it
                # yet).
                # Note that we must do this while the child is blocked so we can be
                # certain that this syscall is not the one that caused the child to
                # process the previous command.
                if child_wants_stdin:
                    self._drain_manager_reads()
                    child_wants_stdin = self._state == State.AWAITING_STDIN_READ

        # Now send the child the next command. We do this after we've let the syscall run,
        # just because there's no reason to keep the child blocked while we do this.
        if child_wants_stdin:
            self._handle_child_wants_stdin()

    def _handle_child_wants_stdin(self):
        logger.debug("%s: Child wants stdin", self._state.name)

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
        logger.debug("%s: Just wrote %s", self._state.name, to_write)

        self._set_state(State.SENT_INPUT_AWAITING_CRLF)

    def _drain_manager_reads(self):
        """
        NOTE: This operation may block.

        Fully drain reads on the manager side of the PTY
        (i.e.: read everything children have read to it).

        There doesn't seem to be any portable way of doing this,
        so we hack it: write a NULL byte into the subsidiary side
        of the PTY, and wait for it to show up on the manager side.

        Hopefully nobody is legitimately writing NULL bytes...
        """
        logger.debug("%s: Draining manager reads", self._state.name)

        null_byte = b"\x00"
        with self._child.with_subsidiary_fd() as subsidiary_fd:
            os.write(subsidiary_fd, null_byte)

        output = b""
        while True:
            output = os.read(self._child.manager_fd, 1024)

            drained = False
            if null_byte in output:
                output = output.replace(null_byte, b"")
                drained = True

            if len(output) > 0:
                self._handle_output(output)

            if drained:
                logger.debug("%s: Drained manager reads", self._state.name)
                break

    def _set_state(self, new_state: State):
        logger.debug("%s: state changing to %s", self._state.name, new_state.name)
        self._state = new_state
