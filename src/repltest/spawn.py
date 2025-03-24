import contextlib
import datetime as dt
import errno
import logging
import os
import pty
import selectors
import signal
import socket
from typing import Callable, Generator

import psutil

from repltest.exceptions import ReplProcessException

logger = logging.getLogger(__name__)


@contextlib.contextmanager
def spawn_child_in_tty(
    args: list[str],
    cleanup_kill_after: dt.timedelta,
    env: dict[str, str] | None,
):
    pid, manager_fd = pty.fork()

    if pid == 0:  # pragma: no cover # coverage can't detect forked children
        if env is None:
            env = dict(os.environ)
        os.execvpe(args[0], args, env)
    else:
        with (
            create_signal_socket([signal.SIGCHLD]) as signal_socket,
            close_fd(manager_fd),
        ):
            child = Child(
                pid=pid,
                signal_fd=signal_socket.fileno(),
                manager_fd=manager_fd,
            )
            try:
                yield child
            finally:
                if child.is_alive():
                    logger.debug(
                        "Child process %s appears to still be running. Attempting to shut it down.",
                        child.pid,
                    )
                    child.graceful_shutdown(
                        term_after=dt.timedelta(seconds=0),
                        kill_after=cleanup_kill_after,
                    )

            assert child.returncode is not None
            if child.returncode != 0:
                raise ReplProcessException(args, child.returncode)


@contextlib.contextmanager
def close_fd(fd: int):
    try:
        yield fd
    finally:
        os.close(fd)


@contextlib.contextmanager
def create_signal_socket(
    signums: list[signal.Signals],
) -> Generator[socket.socket, None, None]:
    # Python's `signal.set_wakeup_fd` doesn't seem to work unless you've
    # actually installed a handler for the relevant signal. This doesn't seem to be documented anywhere :(.
    # The pattern in the wild seems to be to install a dummy handler, e.g.:
    # https://github.com/kovidgoyal/vise/blob/451bc7ecd991f56c9924fd40495f0d9e4b5bb1d5/vise/main.py#L162-L163
    # TODO: file an issue with CPython, perhaps we can at least improve the docs?
    og_handler_by_signal = {}
    for signum in signums:
        og_handler_by_signal[signum] = signal.signal(signum, lambda signum, frame: None)

    signal_socket_r, signal_socket_w = socket.socketpair()
    signal_socket_w.setblocking(False)
    og_fd = signal.set_wakeup_fd(signal_socket_w.fileno())
    try:
        yield signal_socket_r
    finally:
        signal_socket_r.close()
        signal_socket_w.close()

        signal.set_wakeup_fd(og_fd)
        for signum in signums:
            signal.signal(signum, og_handler_by_signal[signum])


class Child:
    def __init__(
        self,
        pid: int,
        signal_fd: int,
        manager_fd: int,
    ):
        self.pid = pid
        self.manager_fd = manager_fd
        self.returncode = None
        self._signal_fd = signal_fd
        self._subsidiary_closed = False
        self._process = psutil.Process(self.pid)

        self._selector = selectors.DefaultSelector()
        self._selector.register(self.manager_fd, selectors.EVENT_READ)
        self._selector.register(signal_fd, selectors.EVENT_READ)

    def wait_for_events(
        self,
        timeout: dt.timedelta | None,
        on_output: Callable[[bytes], None],
        on_subsidiary_closed: Callable[[], None],
    ):
        events = self._selector.select(
            timeout=None if timeout is None else timeout.total_seconds()
        )
        event_fds = {key.fd for key, _mask in events}

        if self.manager_fd in event_fds:
            event_fds.remove(self.manager_fd)
            self._handle_manager_readable(
                on_output=on_output,
                on_subsidiary_closed=on_subsidiary_closed,
            )

        if self._signal_fd in event_fds:
            event_fds.remove(self._signal_fd)
            self._handle_signal_notification()

        assert len(event_fds) == 0, f"Unrecognized FDs: {event_fds}"

    def _handle_manager_readable(
        self,
        on_output: Callable[[bytes], None],
        on_subsidiary_closed: Callable[[], None],
    ):
        assert not self._subsidiary_closed

        try:
            output = os.read(self.manager_fd, 1024)
        except OSError as e:
            # We get an "Input/Output error" when the subsidiary side of the
            # TTY is closed (aka: when no more processes have it open).
            if e.errno == errno.EIO:
                self._subsidiary_closed = True
                on_subsidiary_closed()
                return

            raise  # pragma: no cover

        assert len(output) > 0
        on_output(output)

    def _handle_signal_notification(self):
        """
        Handle a signal notification. Note: the only signal we care about
        is SIGCHILD so we can reap dead children.

        Note: this is *not* running in a signal handler context:
        feel free to do all the things you'd normally do.
        """
        # Just drain the socket, the contents don't really matter.
        os.read(self._signal_fd, 1024)

        assert self.returncode is None, (
            "We shouldn't receive a SIGCHILD notification for a process that's already dead"
        )

        pid, waitstatus = os.waitpid(self.pid, os.WNOHANG)

        # Child has not exited yet (such as a SIGSTOP or SIGCONT).
        if pid == 0:  # pragma: no cover
            return

        # Note: we must record this exit code ASAP. Imagine a
        # scenario where we raise an exception before recording it: some code higher up
        # up may try to ensure the child process is dead, or kill it if it's not.
        # That code would see there's no `self.returncode` recorded, and it would
        # try to stop a nonexistent child process.
        self.returncode = os.waitstatus_to_exitcode(waitstatus)
        logger.debug("Child %s exited with code %s", pid, self.returncode)

        assert pid == self.pid, f"Received SIGCHILD for unexpected child process {pid}"
        assert self.returncode is not None, (
            f"It's not possible for child process {pid} to die twice"
        )

    def is_alive(self) -> bool:
        return self.returncode is None

    def graceful_shutdown(
        self, term_after: dt.timedelta, kill_after: dt.timedelta
    ) -> int:
        """
        Graceful shutdown:

        1. Wait `term_after` for process to exit. If it exits, return the exit code.
        2. Send a SIGTERM.
        3. Wait `kill_after` for process to exit. If it exits, return the exit code.
        4. Send a SIGKILL.
        5. Wait forever for process to exit and return its exit code.
        """
        assert self.returncode is None, (
            f"Cannot shut down already dead process {self.pid}"
        )

        returncode = None

        try:
            returncode = self._process.wait(timeout=term_after.total_seconds())
        except psutil.TimeoutExpired:
            logger.debug("Timed out waiting for %s to exit. Sending SIGTERM", self.pid)
            self._process.terminate()

        if returncode is None:
            try:
                returncode = self._process.wait(timeout=kill_after.total_seconds())
            except psutil.TimeoutExpired:
                logger.debug(
                    "Timed out waiting for %s to exit. Sending SIGKILL", self.pid
                )
                self._process.kill()

        if returncode is None:
            returncode = self._process.wait()

        self.returncode = returncode
        logger.debug("Process %s terminated with return code %s", self.pid, returncode)
        return self.returncode
