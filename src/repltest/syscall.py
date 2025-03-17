from ctypes import CDLL, c_int, c_long, c_uint, get_errno
from os import strerror

__all__ = [
    "pidfd_getfd",
    "kcmp",
]

# Copied from https://unix.stackexchange.com/a/773998
# See https://discuss.python.org/t/add-pidfd-getfd-syscall-to-os-module/19789 for discussion about adding this to `cpython`.
_syscall = CDLL(None, use_errno=True).syscall

# Non-variadic system call number argument:
_syscall.argtypes = [c_long]


SYSCALL_PIDFD_GETFD = 438  # Linux kernel: arch/x86/entry/syscalls/syscall_64.tbl


# TODO: unused?
def pidfd_getfd(pidfd: int, targetfd: int) -> int:
    fd = _syscall(
        SYSCALL_PIDFD_GETFD,
        c_int(pidfd),
        c_int(targetfd),
        c_uint(0),  # Unused "flags" argument.
    )
    if fd == -1:
        errno = get_errno()
        raise OSError(errno, strerror(errno))
    return fd


KCMP_FILE = 0  # Linux kernel: include/uapi/linux/kcmp.h
SYSCALL_KCMP = 312  # Linux kernel: arch/x86/entry/syscalls/syscall_64.tbl


def kcmp(pid1: int, pid2: int, type_: int, idx1: int, idx2: int) -> int:
    result = _syscall(
        SYSCALL_KCMP,
        c_int(pid1),
        c_int(pid2),
        c_int(type_),
        c_uint(idx1),
        c_uint(idx2),
    )
    if result == -1:
        errno = get_errno()
        raise OSError(errno, strerror(errno))
    return result
