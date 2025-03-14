import errno
import os
import socket

from seccomp import (
    ALLOW,
    NOTIFY,
    Arch,
    NotificationResponse,
    SyscallFilter,
    resolve_syscall,
)

from .syscall import pidfd_getfd


def test():
    fake_uid = 4242

    def handle_getuid(notify):
        nonlocal fake_uid
        fake_uid += 1

        print(f"Parent returning bogus uid: {fake_uid}")
        return NotificationResponse(notify, fake_uid, 0, 0)

    def handle_read(notify):
        child_fd, buf_pointer, count, *_ = notify.syscall_args

        # TODO: what if the child process gets interrupted? See "Caveats regarding blocking system calls" in https://man7.org/linux/man-pages/man2/seccomp_unotify.2.html

        parent_copy_of_child_fd = pidfd_getfd(os.pidfd_open(notify.pid), child_fd)
        data = os.read(parent_copy_of_child_fd, count)
        os.close(parent_copy_of_child_fd)

        child_mem_fd = os.open(f"/proc/{notify.pid}/mem", os.O_WRONLY)
        val = os.pwrite(child_mem_fd, data, buf_pointer)
        os.close(child_mem_fd)

        return NotificationResponse(notify, val, 0, 0)

    syscall_handlers = {
        "getuid": handle_getuid,
        "read": handle_read,
    }

    parent_socket, child_socket = socket.socketpair(socket.AF_UNIX)

    pid = os.fork()
    if pid == 0:
        f = SyscallFilter(ALLOW)
        for syscall_name in syscall_handlers.keys():
            f.add_rule(NOTIFY, syscall_name)
        f.load()

        notify_fd = f.get_notify_fd()
        socket.send_fds(child_socket, ["notify_fd".encode()], [notify_fd])

        print("Child about to call getuid")
        val = os.getuid()
        print(f"Child successfully called getuid and got {val}.")

        color = input("Fav color? ")
        print(f"Your favorite color is {color}")

        print("Child about to call getuid")
        val = os.getuid()
        print(f"Child successfully called getuid and got {val}.")

        print("Child exiting")
        quit(0)
    else:
        f = SyscallFilter(ALLOW)

        msg, fds, flags, addr = socket.recv_fds(parent_socket, 1024, 1)
        assert msg == b"notify_fd"
        (notify_fd,) = fds
        f.set_notify_fd(notify_fd)

        while True:
            try:
                notify = f.receive_notify()
            except RuntimeError as e:
                if str(e) == f"Library error (errno = -{errno.ECANCELED})":
                    # Happens when the child goes away.
                    # TODO: file an issue with `libseccomp` to see if there's a less
                    # stringly way of doing this.
                    break
                raise

            handler_by_id = {
                resolve_syscall(Arch(), name): handler
                for name, handler in syscall_handlers.items()
            }
            handler = handler_by_id[notify.syscall]
            response = handler(notify)
            f.respond_notify(response)

        _pid, waitstatus = os.waitpid(pid, 0)
        exitcode = os.waitstatus_to_exitcode(waitstatus)

        if exitcode != 0:
            raise RuntimeError(f"Child exited with {exitcode=}")

        print("Parent about to call os.getuid")
        uid = os.getuid()
        print(f"Parent got {uid=}")


test()
