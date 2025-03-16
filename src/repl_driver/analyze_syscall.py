import ctypes
import os
from typing import Self

import seccomp

from .syscall import KCMP_FILE, kcmp


def _is_same_fd(pid1: int, fd1: int, pid2: int, fd2: int) -> bool:
    return kcmp(pid1, pid2, KCMP_FILE, fd1, fd2) == 0


class PollFd(ctypes.Structure):
    """
    See `struct pollfd` in `poll(2)`.
    """

    _fields_ = [
        ("fd", ctypes.c_int),
        ("events", ctypes.c_short),
        ("revents", ctypes.c_short),
    ]


class Syscall:
    name: str
    could_indicate_desire_to_read_fd: bool

    def indicates_desire_to_read_fd(self, fd: int) -> bool:
        raise NotImplementedError()  # pragma: no cover

    @classmethod
    def parse_seccomp(cls, notify: seccomp.Notification) -> Self:
        raise NotImplementedError()  # pragma: no cover


class ReadSyscall(Syscall):
    name = "read"
    could_indicate_desire_to_read_fd = True

    def __init__(self, pid: int, fd: int, buf_pointer: int, count: int):
        self.pid = pid
        self.fd = fd
        self.buf_pointer = buf_pointer
        self.count = count

    @classmethod
    def parse_seccomp(cls, notify: seccomp.Notification) -> Self:
        fd, buf_pointer, count, *_ = notify.syscall_args

        return cls(pid=notify.pid, fd=fd, buf_pointer=buf_pointer, count=count)

    def indicates_desire_to_read_fd(self, fd: int) -> bool:
        my_pid = os.getpid()
        my_fd = fd
        return _is_same_fd(my_pid, my_fd, self.pid, self.fd)


class PollSyscall(Syscall):
    name = "poll"
    could_indicate_desire_to_read_fd = True

    def __init__(self, pid: int, fds_pointer: int, nfds: int, timeout: int):
        self.pid = pid
        self.fds_pointer = fds_pointer
        self.nfds = nfds
        self.timeout = timeout

    @classmethod
    def parse_seccomp(cls, notify: seccomp.Notification) -> Self:
        fds_pointer, nfds, timeout, *_ = notify.syscall_args
        return cls(pid=notify.pid, fds_pointer=fds_pointer, nfds=nfds, timeout=timeout)

    def indicates_desire_to_read_fd(self, fd: int) -> bool:
        """
        Some processes wait to see that a file descriptor is readable before blocking
        trying to `read()` from it. For example, Python uses `pselect` [0]
        (which I guess `glibc` turns into `poll`?) to do this.

        [0]: https://github.com/python/cpython/blob/v3.13.2/Modules/readline.c#L1416-L1417
        """
        PollFds = PollFd * self.nfds
        poll_fds = PollFds()
        with open(f"/proc/{self.pid}/mem", "rb") as mem_f:
            mem_f.seek(self.fds_pointer)
            count = mem_f.readinto(poll_fds)
            assert count == ctypes.sizeof(PollFds)

        for poll_fd in poll_fds:
            my_pid = os.getpid()
            my_fd = fd
            if _is_same_fd(my_pid, my_fd, self.pid, poll_fd.fd):
                return True

        return False


SYSCALL_CLASSES = Syscall.__subclasses__()

SYSCALLS_THAT_COULD_INDICATE_WANTS_STDIN = [
    cls for cls in SYSCALL_CLASSES if cls.could_indicate_desire_to_read_fd
]


# TODO: need to add `pselect6` for sh.
# <<< assert syscall.name == "pselect6"
# <<< nfds_arg: SyscallArgument = syscall.arguments[0]
# <<< fd_set_arg: SyscallArgument = syscall.arguments[1]
# <<< nfds = cast(int, nfds_arg.value)
# <<<
# <<< # Ignore the end of a select, we're only interested in the start
# <<< # of one (to check if the process is trying to read from stdin).
# <<< if syscall.result is not None:
# <<<     return
# <<<
# <<< fd_set: set[int] = set(
# <<<     x
# <<<     for x in fd_set_arg.readBits(
# <<<         fd_set_arg.value,
# <<<         FD_SETSIZE,
# <<<         format=lambda x: x,  # type: ignore
# <<<     )
# <<<     if int(x) < nfds
# <<< )
# <<< for fd in fd_set:
# <<<     if is_tty(fd):
# <<<         self.input_wanted_newlines_read = self.newlines_read


def get_syscall_from_seccomp_notify(notify: seccomp.Notification) -> Syscall:
    syscall_class_by_id: dict[int, type[Syscall]] = {
        seccomp.resolve_syscall(seccomp.Arch(), syscall.name): syscall
        for syscall in SYSCALL_CLASSES
    }
    cls = syscall_class_by_id[notify.syscall]
    return cls.parse_seccomp(notify)
