import contextlib
import datetime as dt
import errno
import logging
import os
import pty
import selectors
import signal
import socket
from typing import Callable, Generator, Self

import psutil

logger = logging.getLogger(__name__)


def graceful_shutdown(
    process: psutil.Process,
    term_after: dt.timedelta | None,
    kill_after: dt.timedelta | None,
) -> int:
    """
    Graceful shutdown:

    1. Wait `term_after` for process to exit (wait forever if `term_after` is `None`).
       If it exits, return the exit code.
    2. Send a SIGTERM.
    3. Wait `kill_after` for process to exit (wait forever if `kill_after` is `None`).
       If it exits, return the exit code.
    4. Send a SIGKILL.
    5. Wait forever for process to exit and return its exit code.
    """
    exit_code = None

    try:
        term_after_seconds = None if term_after is None else term_after.total_seconds()
        exit_code = process.wait(timeout=term_after_seconds)
    except psutil.TimeoutExpired:
        logger.info("Timed out waiting for %s to exit. Sending SIGTERM", process.pid)
        process.terminate()

    if exit_code is None:
        try:
            kill_after_seconds = (
                None if kill_after is None else kill_after.total_seconds()
            )
            exit_code = process.wait(timeout=kill_after_seconds)
        except psutil.TimeoutExpired:
            logger.warning(
                "Timed out waiting for %s to exit. Sending SIGKILL", process.pid
            )
            process.kill()

    if exit_code is None:
        exit_code = process.wait()

    logger.debug("Process %s terminated with return code %s", process.pid, exit_code)
    return exit_code


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
    with signal_socket_r, signal_socket_w:
        signal_socket_w.setblocking(False)
        og_fd = signal.set_wakeup_fd(
            signal_socket_w.fileno(),
            # Urg, signal handling is messy. From the Pythond docs [0]:
            # > In the second approach, we use the wakeup fd only for wakeups,
            # > and ignore the actual byte values. [...] If you use this approach,
            # > then you should set `warn_on_full_buffer=False`, so that your users
            # > are not confused by spurious warning messages.
            # [0]: https://docs.python.org/3/library/signal.html#signal.set_wakeup_fd
            warn_on_full_buffer=False,
        )
        try:
            yield signal_socket_r
        finally:
            signal.set_wakeup_fd(og_fd)

            for signum in signums:
                signal.signal(signum, og_handler_by_signal[signum])


class RunningChild:
    def __init__(
        self,
        pid: int,
        signal_fd: int,
        manager_fd: int,
    ):
        self.pid = pid
        self.manager_fd = manager_fd
        self.exit_code = None
        self._signal_fd = signal_fd
        self._subsidiary_closed = False

        self._selector = selectors.DefaultSelector()
        self._selector.register(self.manager_fd, selectors.EVENT_READ)
        self._selector.register(signal_fd, selectors.EVENT_READ)

    def wait_for_events(
        self,
        timeout: dt.timedelta | None,
        on_output: Callable[[Self, bytes], None],
        on_subsidiary_closed: Callable[[Self], None],
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
        on_output: Callable[[Self, bytes], None],
        on_subsidiary_closed: Callable[[Self], None],
    ):
        assert not self._subsidiary_closed

        try:
            output = os.read(self.manager_fd, 1024)
        except OSError as e:
            # We get an "Input/Output error" when the subsidiary side of the
            # TTY is closed (aka: when no more processes have it open).
            if e.errno == errno.EIO:
                self._subsidiary_closed = True
                on_subsidiary_closed(self)
                return

            raise  # pragma: no cover

        assert len(output) > 0
        on_output(self, output)

    def _handle_signal_notification(self):
        """
        Handle a signal notification. Note: the only signal we care about
        is SIGCHILD so we can reap dead children.

        Note: this is *not* running in a signal handler context:
        feel free to do all the things you'd normally do.
        """
        # Just drain the socket, the contents don't really matter.
        # See comment about in `create_signal_socket` about `warn_on_full_buffer=False`.
        os.read(self._signal_fd, 1024)

        assert self.exit_code is None, (
            "We shouldn't receive a SIGCHILD notification for a process that's already dead"
        )

        pid, waitstatus = os.waitpid(self.pid, os.WNOHANG)

        # Child has not exited yet (such as a SIGSTOP or SIGCONT).
        if pid == 0:  # pragma: no cover
            return

        # Note: we must record this exit code ASAP. Imagine a
        # scenario where we raise an exception before recording it: some code higher up
        # up may try to ensure the child process is dead, or kill it if it's not.
        # That code would see there's no `self.exit_code` recorded, and it would
        # try to stop a nonexistent child process.
        self.exit_code = os.waitstatus_to_exitcode(waitstatus)
        logger.debug("Child %s exited with code %s", pid, self.exit_code)

        assert pid == self.pid, f"Received SIGCHILD for unexpected child process {pid}"
        assert self.exit_code is not None, (
            f"It's not possible for child process {pid} to die twice"
        )


class Child:
    def __init__(
        self,
        entrypoint: list[str],
        cleanup_term_after: dt.timedelta | None,
        cleanup_kill_after: dt.timedelta | None,
        env: dict[str, str] | None,
    ):
        self._entrypoint = entrypoint
        self._cleanup_term_after = cleanup_term_after
        self._cleanup_kill_after = cleanup_kill_after
        self._env = env
        self.exit_code = None

    @contextlib.contextmanager
    def spawn(self) -> Generator[RunningChild, None, None]:
        pid, manager_fd = pty.fork()

        if pid == 0:  # pragma: no cover # coverage can't detect forked children
            env = dict(os.environ) if self._env is None else self._env
            os.execvpe(self._entrypoint[0], self._entrypoint, env)
        else:
            process = None
            try:
                with (
                    create_signal_socket([signal.SIGCHLD]) as signal_socket,
                    close_fd(manager_fd),
                ):
                    child = RunningChild(
                        pid=pid,
                        signal_fd=signal_socket.fileno(),
                        manager_fd=manager_fd,
                    )
                    process = psutil.Process(child.pid)

                    yield child

                    self.exit_code = child.exit_code
            finally:
                if process is not None and self.exit_code is None:
                    logger.info(
                        "Child process %s appears to still be running. Attempting to shut it down.",
                        process.pid,
                    )
                    self.exit_code = graceful_shutdown(
                        process=process,
                        term_after=self._cleanup_term_after,
                        kill_after=self._cleanup_kill_after,
                    )

            assert self.exit_code is not None
