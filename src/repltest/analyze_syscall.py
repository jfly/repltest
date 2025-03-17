import ctypes
import os
from typing import Self

import psutil
import seccomp


def _is_same_fd(pid1: int, fd1: int, pid2: int, fd2: int) -> bool:
    """
    Check if fd1 in pid1 points at the same file as fd2 in pid2.
    """
    pid1_openfile_by_fd = {
        f.fd: f for f in psutil.Process(pid1).open_files(only_regular=False)
    }
    pid2_openfile_by_fd = {
        f.fd: f for f in psutil.Process(pid2).open_files(only_regular=False)
    }
    return pid1_openfile_by_fd[fd1].path == pid2_openfile_by_fd[fd2].path


class Syscall:
    name: str
    syscall_args: list
    could_indicate_desire_to_read_fd: bool

    def indicates_desire_to_read_fd(self, fd: int) -> bool:
        raise NotImplementedError()  # pragma: no cover

    @classmethod
    def parse_seccomp(cls, notify: seccomp.Notification) -> Self:
        raise NotImplementedError()  # pragma: no cover

    def __str__(self) -> str:
        pretty_args = ", ".join(map(repr, self.syscall_args))
        return f"{self.name}({pretty_args})"


class ReadSyscall(Syscall):
    name = "read"
    could_indicate_desire_to_read_fd = True

    def __init__(self, pid: int, syscall_args: list):
        self.pid = pid
        self.syscall_args = syscall_args
        self.fd, self.buf_pointer, self.count, *_ = syscall_args

    @classmethod
    def parse_seccomp(cls, notify: seccomp.Notification) -> Self:
        return cls(notify.pid, notify.syscall_args)

    def indicates_desire_to_read_fd(self, fd: int) -> bool:
        my_pid = os.getpid()
        my_fd = fd
        return _is_same_fd(my_pid, my_fd, self.pid, self.fd)


class PollFd(ctypes.Structure):
    """
    See `struct pollfd` in `poll(2)`.
    """

    _fields_ = [
        ("fd", ctypes.c_int),
        ("events", ctypes.c_short),
        ("revents", ctypes.c_short),
    ]


class PollSyscall(Syscall):
    name = "poll"
    could_indicate_desire_to_read_fd = True

    def __init__(self, pid: int, syscall_args: list):
        self.pid = pid
        self.syscall_args = syscall_args
        self.fds_pointer, self.nfds, self.timeout, *_ = syscall_args

    @classmethod
    def parse_seccomp(cls, notify: seccomp.Notification) -> Self:
        return cls(notify.pid, notify.syscall_args)

    def indicates_desire_to_read_fd(self, fd: int) -> bool:
        """
        Some processes wait to see that a file descriptor is readable before blocking
        trying to `read()` from it.
        """
        my_pid = os.getpid()
        my_fd = fd

        PollFds = PollFd * self.nfds
        poll_fds = PollFds()
        with open(f"/proc/{self.pid}/mem", "rb") as mem_f:
            mem_f.seek(self.fds_pointer)
            count = mem_f.readinto(poll_fds)
            assert count == ctypes.sizeof(PollFds)

        for poll_fd in poll_fds:
            if _is_same_fd(my_pid, my_fd, self.pid, poll_fd.fd):
                return True

        return False


# glibc defines this as a `long int`:
# https://sourceware.org/git/?p=glibc.git;a=blob;f=misc/sys/select.h;h=d2cdc0f1cdb82f16c61d8#l49
FdMask = ctypes.c_long


class FdSet(ctypes.Structure):
    """
    This type is opaque in `man select(2)`:
        `typedef ... fd_set`

    I reconstructed this definition from glibc's source code.
    """

    # https://sourceware.org/git/?p=glibc.git;a=blob;f=bits/typesizes.h;h=b6db5c3637702a760f8318881342f7c327ed3fe0;hb=HEAD#l92
    FD_SETSIZE = 1024

    # https://sourceware.org/git/?p=glibc.git;a=blob;f=misc/sys/select.h;h=d2cdc0f1cdb82f16c61d8#l54
    NFDBITS = 8 * ctypes.sizeof(FdMask)

    _fields_ = [
        # https://sourceware.org/git/?p=glibc.git;a=blob;f=misc/sys/select.h;h=d2cdc0f1cdb82f16c61d#l64
        ("fds_bits", FdMask * (FD_SETSIZE // NFDBITS)),
    ]


class PselectSyscall(Syscall):
    name = "pselect6"
    could_indicate_desire_to_read_fd = True

    def __init__(
        self,
        pid: int,
        syscall_args: list,
    ):
        self.pid = pid
        self.syscall_args = syscall_args
        (
            self.nfds,
            self.readfds_pointer,
            self.writefds_pointer,
            self.exceptfds_pointer,
            self.timeout_pointer,
            self.sigmask_pointer,
        ) = syscall_args

    @classmethod
    def parse_seccomp(cls, notify: seccomp.Notification) -> Self:
        return cls(notify.pid, notify.syscall_args)

    def _load_fd_set(self, pointer: int) -> set[int]:
        fd_set = FdSet()
        with open(f"/proc/{self.pid}/mem", "rb") as mem_f:
            mem_f.seek(pointer)
            count = mem_f.readinto(fd_set)
            assert count == ctypes.sizeof(FdSet)

        # A FdSet struct represents which FDs are in the set as a
        # list of "bitsets" where bit N being 1 means that FD N is
        # in the set.
        result_set = set()
        for potential_fd in range(self.nfds):
            nth_bitset = potential_fd // FdSet.NFDBITS
            bitoffset = potential_fd % FdSet.NFDBITS

            bitset = fd_set.fds_bits[nth_bitset]
            if (bitset >> bitoffset) & 1 == 1:
                result_set.add(potential_fd)

        return result_set

    def indicates_desire_to_read_fd(self, fd: int) -> bool:
        my_pid = os.getpid()
        my_fd = fd

        read_fd_set = self._load_fd_set(self.readfds_pointer)

        for fd in read_fd_set:
            if _is_same_fd(my_pid, my_fd, self.pid, fd):
                return True

        return False  # <<< not covered


SYSCALL_CLASSES = Syscall.__subclasses__()

SYSCALLS_THAT_COULD_INDICATE_WANTS_STDIN = [
    cls for cls in SYSCALL_CLASSES if cls.could_indicate_desire_to_read_fd
]


def get_syscall_from_seccomp_notify(notify: seccomp.Notification) -> Syscall:
    syscall_class_by_id: dict[int, type[Syscall]] = {
        seccomp.resolve_syscall(seccomp.Arch(), syscall.name): syscall
        for syscall in SYSCALL_CLASSES
    }
    cls = syscall_class_by_id[notify.syscall]
    return cls.parse_seccomp(notify)
