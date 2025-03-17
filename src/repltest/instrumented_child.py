import contextlib
import datetime as dt
import errno
import logging
import os
import pty
import selectors
import signal
import socket
from typing import Callable, ContextManager, Generator

import seccomp

from . import analyze_syscall

logger = logging.getLogger(__name__)

# TODO: contribute upstream to `libseccomp`?
# From `tools/include/uapi/linux/seccomp.h`
SECCOMP_USER_NOTIF_FLAG_CONTINUE = 1 << 0


@contextlib.contextmanager
def instrumented_child(
    args: list[str],
    syscalls_to_instrument: list[type[analyze_syscall.Syscall]],
):
    parent_socket, child_socket = socket.socketpair()
    pid, manager_fd = pty.fork()

    if pid == 0:  # pragma: no cover # coverage can't detect forked children
        parent_socket.close()

        with child_socket:
            f = seccomp.SyscallFilter(seccomp.ALLOW)
            for syscall in syscalls_to_instrument:
                f.add_rule(seccomp.NOTIFY, syscall.name)
            f.load()

            notify_fd = f.get_notify_fd()
            socket.send_fds(
                child_socket,
                [b"notify_fd"],
                [notify_fd],
            )

        os.execvp(args[0], args)
    else:
        child_socket.close()

        with (
            create_signal_socket([signal.SIGCHLD]) as signal_socket,
            create_syscall_filter(parent_socket) as syscall_filter,
            close_fd(manager_fd),
        ):
            yield InstrumentedChild(
                pid=pid,
                signal_fd=signal_socket.fileno(),
                manager_fd=manager_fd,
                syscall_filter=syscall_filter,
            )


@contextlib.contextmanager
def close_fd(fd: int):
    try:
        yield fd
    finally:
        os.close(fd)


@contextlib.contextmanager
def create_syscall_filter(
    receive_notify_fd_socket: socket.socket,
) -> Generator[seccomp.SyscallFilter, None, None]:
    # Receive the `notify_fd` from the child.
    with receive_notify_fd_socket:
        msg, fds, _flags, _addr = socket.recv_fds(receive_notify_fd_socket, 1024, 1)
    assert msg == b"notify_fd", f"Unexpected message: {msg}"
    (notify_fd,) = fds

    syscall_filter = seccomp.SyscallFilter(seccomp.ALLOW)
    syscall_filter.set_notify_fd(notify_fd)

    try:
        yield syscall_filter
    finally:
        syscall_filter.reset()
        # `libseccomp::seccomp_reset` only resets global state if `ctx == NULL`: https://github.com/seccomp/libseccomp/blob/v2.6.0/src/api.c#L337
        # `SyscallFilter::reset` always passes a non-null `ctx`: https://github.com/seccomp/libseccomp/blob/v2.6.0/src/python/seccomp.pyx#L640
        # TODO: file an issue with `libseccomp` asking about how to clean up.
        # TODO: file an issue with `libseccomp` asking to make it impossible
        #       to create two `SyscallFilter`s in parallel (at least, I'm
        #       pretty sure that's a bad idea).
        os.close(notify_fd)
        syscall_filter.set_notify_fd(-1)


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


class InstrumentedChild:
    def __init__(
        self,
        pid: int,
        signal_fd: int,
        manager_fd: int,
        syscall_filter: seccomp.SyscallFilter,
    ):
        self.pid = pid
        self.manager_fd = manager_fd
        self._signal_fd = signal_fd
        self.returncode = None
        self._subsidiary_closed = False

        self._syscall_filter = syscall_filter
        self._notify_fd = self._syscall_filter.get_notify_fd()

        self._selector = selectors.DefaultSelector()
        self._selector.register(self.manager_fd, selectors.EVENT_READ)
        self._selector.register(self._notify_fd, selectors.EVENT_READ)
        self._selector.register(signal_fd, selectors.EVENT_READ)

    @contextlib.contextmanager
    def with_subsidiary_fd(self):
        subsidiary_path = os.ptsname(self.manager_fd)
        subsidiary_fd = os.open(subsidiary_path, os.O_RDWR)
        try:
            yield subsidiary_fd
        finally:
            os.close(subsidiary_fd)

    def wait_for_events(
        self,
        timeout: dt.timedelta | None,
        on_output: Callable[[bytes], None],
        on_subsidiary_closed: Callable[[], None],
        on_syscall: Callable[[ContextManager[analyze_syscall.Syscall]], None],
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

        # Note: we intentionally process notify_fd last. Why?
        # The syscall event handlers could change the state
        # of the world and file descriptors that were previously
        # readable/writeable may no longer be readable/writeable
        # (for example, see `_drain_manager_reads`).
        if self._notify_fd in event_fds:
            event_fds.remove(self._notify_fd)
            self._handle_notify(on_syscall)

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

    def _handle_notify(
        self,
        on_syscall: Callable[[ContextManager[analyze_syscall.Syscall]], None],
    ) -> bool:
        """
        Handle syscall notification from seccomp.
        Note that the child process is blocked until we return a response.

        Returns True if we invoked `on_sycall` (which could not happen if
        the notify is stale).
        """
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
                logger.debug("Tried to receive a stale notify. Ignoring.")

                # We did not invoke the callback.
                return False

            raise  # pragma: no cover

        syscall = analyze_syscall.get_syscall_from_seccomp_notify(notify)

        attempted_to_respond_to_sycall = False

        @contextlib.contextmanager
        def with_syscall():
            yield syscall

            nonlocal attempted_to_respond_to_sycall
            attempted_to_respond_to_sycall = True

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
                    logger.debug("Tried to respond to a stale notify. Ignoring.")
                    return

                raise

        on_syscall(with_syscall())

        assert attempted_to_respond_to_sycall, (
            "on_syscall callback never did anything with the syscall! It must handle the syscall in order to unblock the child process."
        )
        return True

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
