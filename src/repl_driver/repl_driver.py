import datetime as dt
import enum
import errno
import logging
import os
import pty
import selectors
import signal
import socket
import termios
import time
from typing import Any, Callable

import seccomp

from . import analyze_syscall
from .exceptions import ReplTimeoutException

logger = logging.getLogger(__name__)


def get_special_char_vals(tty: int) -> set[int]:
    # From `help(termios.tcgetattr)`:
    # > cc is a list of the tty special characters (each a string of
    # > length 1, except the items with indices VMIN and VTIME, which are
    # > integers when these fields are defined
    cc: list[bytes | int]
    _iflag, _oflag, _cflag, _lflag, _ispeed, _ospeed, cc = termios.tcgetattr(tty)
    return set(ord(c) for c in cc if not isinstance(c, int))


def is_echo_enabled(tty: int) -> bool:
    _iflag, _oflag, _cflag, lflag, _ispeed, _ospeed, _cc = termios.tcgetattr(tty)
    return lflag & termios.ECHO != 0


# TODO: contribute upstream to `libseccomp`?
# From `tools/include/uapi/linux/seccomp.h`
SECCOMP_USER_NOTIF_FLAG_CONTINUE = 1 << 0


class State(enum.Enum):
    AWAITING_STDIN_READ = enum.auto()
    SENT_INPUT_AWAITING_CRLF = enum.auto()
    SENT_INPUT_AWAITING_OUTPUT = enum.auto()
    DONE = enum.auto()


class ReplDriver:
    def __init__(
        self,
        args: list[str],
        input_callback: Callable[[], bytes],
        on_output: Callable[[bytes], Any],
        timeout: dt.timedelta | None = None,
    ):
        super().__init__()
        self._input_callback = input_callback
        self._on_output = on_output
        self._args = args
        self._timeout = timeout
        self._state = State.AWAITING_STDIN_READ

        parent_socket, child_socket = socket.socketpair()
        pid, manager_fd = pty.fork()

        if pid == 0:  # pragma: no cover # coverage can't detect forked children
            parent_socket.close()
            with child_socket:
                f = seccomp.SyscallFilter(seccomp.ALLOW)
                for syscall in analyze_syscall.SYSCALLS_THAT_COULD_INDICATE_WANTS_STDIN:
                    f.add_rule(seccomp.NOTIFY, syscall.name)
                f.load()

                notify_fd = f.get_notify_fd()
                socket.send_fds(
                    child_socket,
                    [b"notify_fd, subsidiary_fd"],
                    [notify_fd, pty.STDIN_FILENO],
                )

            os.execvp(self._args[0], self._args)
        else:
            child_socket.close()
            with parent_socket:
                msg, fds, _flags, _addr = socket.recv_fds(parent_socket, 1024, 2)

            assert msg == b"notify_fd, subsidiary_fd", f"Unexpected message: {msg}"

            self._notify_fd, self._subsidiary_fd = fds
            self._child_pid = pid
            self._manager_fd = manager_fd

            self._syscall_filter = seccomp.SyscallFilter(seccomp.ALLOW)
            self._syscall_filter.set_notify_fd(self._notify_fd)

            # Python's `signal.set_wakeup_fd` doesn't seem to work unless you've
            # actually installed a handler for the relevant signal. This doesn't seem to be documented anywhere :(.
            # The pattern in the wild seems to be to install a dummy handler, e.g.:
            # https://github.com/kovidgoyal/vise/blob/451bc7ecd991f56c9924fd40495f0d9e4b5bb1d5/vise/main.py#L162-L163
            # TODO: file an issue with CPython, perhaps we can at least improve the docs?
            og_sigchild_handler = signal.signal(
                signal.SIGCHLD, lambda signum, frame: None
            )

            self._signal_socket_r, signal_socket_w = socket.socketpair()
            signal_socket_w.setblocking(False)
            og_fd = signal.set_wakeup_fd(signal_socket_w.fileno())

            try:
                with self._signal_socket_r, signal_socket_w:
                    self._loop()
            finally:
                signal.set_wakeup_fd(og_fd)
                signal.signal(signal.SIGCHLD, og_sigchild_handler)

                self._syscall_filter.reset()
                # `libseccomp::seccomp_reset` only resets global state if `ctx == NULL`: https://github.com/seccomp/libseccomp/blob/v2.6.0/src/api.c#L337
                # `SyscallFilter::reset` always passes a non-null `ctx`: https://github.com/seccomp/libseccomp/blob/v2.6.0/src/python/seccomp.pyx#L640
                # TODO: file an issue with `libseccomp` asking about how to clean up.
                # TODO: file an issue with `libseccomp` asking to make it impossible
                #       to create two `SyscallFilter`s in parallel (at least, I'm
                #       pretty sure that's a bad idea).
                os.close(self._notify_fd)
                self._syscall_filter.set_notify_fd(-1)
                del self._notify_fd

                os.close(self._manager_fd)
                del self._manager_fd
                os.close(self._subsidiary_fd)
                del self._subsidiary_fd

    def _handle_child_wants_stdin(self):
        logger.debug("%s: Child wants stdin", self._state.name)
        self._drain_manager_reads()

        to_write = self._input_callback()
        assert len(to_write) > 0, "Input must be longer than 0 bytes"

        special_char_vals = get_special_char_vals(self._manager_fd)
        has_special_chars = len(special_char_vals & set(to_write)) > 0
        if has_special_chars:
            assert len(to_write) == 1, (
                "We currently only support sending exactly 1 special character at a time. "
            )
        else:
            assert not has_special_chars
            assert to_write.endswith(b"\n"), (
                "Input without special chars must end in a newline"
            )

        os.write(self._manager_fd, to_write)
        logger.debug("%s: Just wrote %s", self._state.name, to_write)

        if is_echo_enabled(self._manager_fd):
            self._set_state(State.SENT_INPUT_AWAITING_CRLF)
        else:
            self._set_state(State.SENT_INPUT_AWAITING_OUTPUT)

    def _kick_foreground_process(self):
        """
        If the the foreground process (the process attached to the TTY)
        is stuck in a blocking syscall, break it out of that syscall.

        We need to do this in case we ignored a `read()` from a child
        process while we were sending it input. See "Ignoring child syscall"
        in `_handle_notify` for details.
        """
        fg_pid = os.tcgetpgrp(self._manager_fd)
        logger.debug("%s: Kicking %s", self._state.name, fg_pid)
        os.kill(fg_pid, signal.SIGSTOP)
        os.kill(fg_pid, signal.SIGCONT)
        logger.debug("%s: Kicked %s", self._state.name, fg_pid)

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
        os.write(self._subsidiary_fd, null_byte)

        output = b""
        while True:
            output = os.read(self._manager_fd, 1024)

            drained = False
            if null_byte in output:
                output = output.replace(null_byte, b"")
                drained = True

            if len(output) > 0:
                logger.debug("%s: Just read %s", self._state.name, output)
                self._on_output(output)

            if drained:
                logger.debug("%s: Drained manager reads", self._state.name)
                break

    def _handle_manager_readable(self):
        """
        Called when the manager fd is readable (aka: when a
        child process has written some output to the PTY).
        """
        output = os.read(self._manager_fd, 1024)

        assert len(output) > 0

        logger.debug("%s: Just read %s", self._state.name, output)
        self._on_output(output)

        if self._state == State.SENT_INPUT_AWAITING_CRLF:
            if output.endswith(b"\r\n"):
                self._set_state(State.SENT_INPUT_AWAITING_OUTPUT)
            elif b"\r\n" in output:
                self._set_state(State.AWAITING_STDIN_READ)
                self._kick_foreground_process()
        elif self._state == State.SENT_INPUT_AWAITING_OUTPUT:
            self._set_state(State.AWAITING_STDIN_READ)
            self._kick_foreground_process()

    def _handle_notify(self):
        try:
            notify = self._syscall_filter.receive_notify()
        except RuntimeError as e:
            if (
                str(e) == f"Library error (errno = -{errno.ECANCELED})"
                or str(e) == f"Library error (errno = -{errno.ENOENT})"
            ):
                # Happens if the notification is no longer valid (if the
                # process was interrupted during its syscall).
                # TODO: file an issue with `libseccomp` to see if there's a less
                # stringly way of doing this.
                logger.debug(
                    "%s: Tried to receive a stale notify. Ignoring.", self._state.name
                )
                return

            raise  # pragma: no cover

        child_wants_stdin = False
        match self._state:
            case State.AWAITING_STDIN_READ:
                syscall = analyze_syscall.get_syscall_from_seccomp_notify(notify)
                child_wants_stdin = syscall.indicates_desire_to_read_fd(
                    self._subsidiary_fd
                )
            case (
                State.SENT_INPUT_AWAITING_CRLF | State.SENT_INPUT_AWAITING_OUTPUT
            ):  # pragma: no cover # Doesn't happen every time.
                # We've just sent input to the child, but we haven't confirmed yet that the
                # child has read that input. We ignore any syscalls the child makes until
                # we've verified the child has processed our input.
                # Note: this could cause the child to get blocked (perhaps in a `read()`).
                # See `_kick_foreground_process` for how we handle that situation
                logger.debug("%s: Ignoring child syscall", self._state.name)
            case _:  # pragma: no cover
                assert False, f"Unrecognized state: {self._state}"

        continue_response = seccomp.NotificationResponse(
            notify,
            val=0,
            error=0,
            flags=SECCOMP_USER_NOTIF_FLAG_CONTINUE,
        )
        try:
            self._syscall_filter.respond_notify(continue_response)
        except RuntimeError as e:  # pragma: no cover
            if (
                str(e) == f"Library error (errno = -{errno.ECANCELED})"
                or str(e) == f"Library error (errno = -{errno.ENOENT})"
            ):
                # Happens if the notification is no longer valid (if the
                # process was interrupted during its syscall).
                # TODO: file an issue with `libseccomp` to see if there's a less
                # stringly way of doing this.
                logger.debug(
                    "%s: Tried to respond to a stale notify. Ignoring.",
                    self._state.name,
                )
                return

            raise

        if child_wants_stdin:
            self._handle_child_wants_stdin()

    def _handle_signal(self):
        # Just drain the socket, the contents don't really matter.
        self._signal_socket_r.recv(1024)

        logger.debug(
            "%s: Checking if child %s has exited", self._state.name, self._child_pid
        )
        pid, waitstatus = os.waitpid(self._child_pid, os.WNOHANG)
        if pid == 0:  # pragma: no cover
            logger.debug(
                "%s: Child %s has not exited. Continuing.",
                self._state.name,
                self._child_pid,
            )
            return

        self.returncode = os.waitstatus_to_exitcode(waitstatus)
        logger.debug(
            "%s: Child %s exited with code %s",
            self._state.name,
            self._child_pid,
            self.returncode,
        )

        # Make sure we've read everything from the
        # PTY before exiting.
        self._drain_manager_reads()

        self._set_state(State.DONE)

    def _set_state(self, new_state: State):
        logger.debug("%s: state changing to %s", self._state.name, new_state.name)
        self._state = new_state

    def _loop(self):
        sel = selectors.DefaultSelector()
        sel.register(
            self._manager_fd, selectors.EVENT_READ, data=self._handle_manager_readable
        )
        sel.register(self._notify_fd, selectors.EVENT_READ, data=self._handle_notify)
        sel.register(
            self._signal_socket_r, selectors.EVENT_READ, data=self._handle_signal
        )

        start_ts = time.monotonic()

        while self._state != State.DONE:
            if self._timeout is not None:
                elapsed_seconds = time.monotonic() - start_ts
                budget_seconds = self._timeout.total_seconds() - elapsed_seconds
            else:  # pragma: no cover # we always specify a timeout in tests
                budget_seconds = None

            events = sel.select(timeout=budget_seconds)

            if self._timeout is not None:
                elapsed_seconds = time.monotonic() - start_ts
                if elapsed_seconds > self._timeout.total_seconds():
                    raise ReplTimeoutException()

            for key, _mask in events:
                old_state = self._state

                # Invoke the relevant handler.
                key.data()

                # If the state has changed, restart the `select` loop. Some of the handlers
                # call functions like `_drain_manager_reads` which could make other handlers block
                # (such as `_handle_manager_readable`, which assumes the manager fd is readable).
                # Solution: these things only happen when the state changes. If the state changed,
                # restart the loop. Any events will still be waiting for us there.
                if old_state != self._state:
                    logger.debug(
                        "%s: State changed from %s to %s. Restarting loop",
                        self._state.name,
                        old_state,
                        self._state,
                    )
                    break

    def check_returncode(self):
        assert self.returncode == 0, f"Process exited with returncode {self.returncode}"
