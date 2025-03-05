import os
import selectors
import threading
import time
from typing import Any, Callable, cast

from ptrace.binding import ptrace_traceme
from ptrace.debugger import (
    NewProcessEvent,
    ProcessExit,
    ProcessSignal,
    PtraceDebugger,
    PtraceProcess,
)
from ptrace.debugger.process import SyscallState
from ptrace.func_call import FunctionCallOptions
from ptrace.syscall import PtraceSyscall, SyscallArgument
from ptrace.syscall.linux_constants import FD_SETSIZE
from ptrace.tools import signal_to_exitcode

DEBUG = True  # <<<

# TODO: what happens if someone tries to use this under ptrace?


def is_tty(fd: int):
    # TODO: handle scenario where stdin is not a TTY
    return fd == 0


class ReadWatcher(threading.Thread):
    def __init__(self, args: list[str]):
        super().__init__(daemon=True)

        self._syscall_dispatch = {
            "read": self.handle_read,
            "pselect6": self.handle_pselect6,
        }

        self._manager_fd_cv = threading.Condition()
        self._manager_fd = None
        self._args = args
        self.newlines_read = 0
        self.input_wanted_newlines_read = -1

    def handle_syscall(self, syscall: PtraceSyscall):
        if syscall.name in self._syscall_dispatch:
            self._syscall_dispatch[syscall.name](syscall)

    def handle_pselect6(self, syscall: PtraceSyscall):
        """
        Some processes wait to see that `stdin` is readable before blocking
        trying to `read()` from it. For example, Python uses `pselect6` [0]
        (which `glibc` seems to turn into `pselect6`) to do this.

        [0]: https://github.com/python/cpython/blob/v3.13.2/Modules/readline.c#L1416-L1417
        """
        assert syscall.name == "pselect6"
        nfds_arg: SyscallArgument = syscall.arguments[0]
        fd_set_arg: SyscallArgument = syscall.arguments[1]
        nfds = cast(int, nfds_arg.value)

        # Ignore the end of a select, we're only interested in the start
        # of one (to check if the process is trying to read from stdin).
        if syscall.result is not None:
            return

        fd_set: set[int] = set(
            x
            for x in fd_set_arg.readBits(
                fd_set_arg.value,
                FD_SETSIZE,
                format=lambda x: x,  # type: ignore
            )
            if int(x) < nfds
        )
        for fd in fd_set:
            if is_tty(fd):
                self.input_wanted_newlines_read = self.newlines_read

    def handle_read(self, syscall: PtraceSyscall):
        assert syscall.name == "read"
        fd_arg: SyscallArgument = syscall.arguments[0]
        buf_arg: SyscallArgument = syscall.arguments[1]

        assert fd_arg.value is not None
        fd: int = fd_arg.value

        if not is_tty(fd):
            return

        if syscall.result is None:
            self.input_wanted_newlines_read = self.newlines_read
        else:
            bytes_read = syscall.result
            buf_contents: bytes = syscall.process.readBytes(buf_arg.value, bytes_read)
            for ch in buf_contents:
                if ch in [
                    ord("\n"),
                    ord("\r"),  # TODO: understand the deal with \n vs \r here.
                ]:
                    self.newlines_read += 1

    def display_syscall(self, syscall: PtraceSyscall):
        text = syscall.format()
        if syscall.result is not None:
            text = "%-40s = %s" % (text, syscall.result_text)
        prefix = []
        prefix.append("[%0.2f]" % time.time())
        prefix.append("[%s]" % syscall.process.pid)
        if prefix:
            text = "".join(prefix) + " " + text
        print(text)

    def syscall(self, process: PtraceProcess):
        state: SyscallState = process.syscall_state

        syscall_options = FunctionCallOptions()

        syscall = state.event(syscall_options)
        if syscall is not None:
            if DEBUG and syscall.result is None:
                self.display_syscall(syscall)

            # <<< self.handle_syscall(syscall)

            if DEBUG and syscall.result is not None:
                self.display_syscall(syscall)

        # Break at next syscall
        process.syscall()

    def ignore_syscall(self, syscall: PtraceSyscall):
        return False  # <<<
        # <<< return syscall.name not in self._syscall_dispatch.keys()

    def get_manager_fd(self) -> int:
        """
        Get the manager end of the psuedoterminal allocated for this process.

        If one has not been created yet, will block until it has.
        """
        assert self.is_alive()

        with self._manager_fd_cv:
            self._manager_fd_cv.wait_for(lambda: self._manager_fd is not None)

            fd = self._manager_fd
            assert fd is not None
            return fd

    def run(self):
        # <<< pid, fd = pty.fork()
        pid = os.fork()  # <<<

        if pid == 0:
            ptrace_traceme()
            os.execvp(self._args[0], self._args)
        else:
            with self._manager_fd_cv:
                # <<< self._manager_fd = fd
                self._manager_fd = "BOGUS"  # <<<
                self._manager_fd_cv.notify()

        debugger = PtraceDebugger()
        debugger.traceFork()

        process = debugger.addProcess(pid, is_attached=True)
        process.syscall_state.ignore_callback = self.ignore_syscall  # type: ignore # urg

        process.syscall()

        exitcode = 0
        while True:
            # If there are no more child/descendant processes, exit.
            if len(debugger.list) == 0:
                break

            # Wait until the next syscall.
            try:
                event = debugger.waitSyscall()
            except ProcessExit as event:
                if event.exitcode is not None:
                    exitcode = event.exitcode
                continue
            except ProcessSignal as event:
                event.process.syscall(event.signum)
                exitcode = signal_to_exitcode(event.signum)
                continue
            except NewProcessEvent as event:
                process = event.process
                process.syscall_state.ignore_callback = self.ignore_syscall  # type: ignore # urg
                process.syscall()
                assert process.parent is not None
                process.parent.syscall()
                continue

            # Process syscall enter or exit
            assert event is not None
            self.syscall(event.process)

        self.exitcode = exitcode
        debugger.quit()


class ReplDriver:
    def __init__(
        self,
        args: list[str],
        input_callback: Callable[[], bytes],
        on_output: Callable[[bytes], Any],
    ):
        super().__init__()
        self._input_callback = input_callback
        self._on_output = on_output
        self._args = args

    def spawn(self):
        watcher = ReadWatcher(self._args)
        watcher.start()

        manager_fd = watcher.get_manager_fd()

        newlines_sent = 0

        sel = selectors.DefaultSelector()
        # <<< os.set_blocking(manager_fd, False)
        # <<< sel.register(manager_fd, selectors.EVENT_READ)

        while True:
            # <<< print("about to call select...", end="")  # <<<
            events = sel.select(timeout=0.1)
            # <<< print(f" done: {len(events)}")  # <<<

            if not watcher.is_alive():
                break

            for key, _mask in events:
                assert key.fd == manager_fd
                try:
                    output = os.read(key.fd, 1024)
                except OSError:
                    # This happens at EOF.
                    break

                self._on_output(output)

            child_has_read_everything = newlines_sent == watcher.newlines_read
            child_wants_input = (
                watcher.newlines_read == watcher.input_wanted_newlines_read
            )
            # <<< print(f"{child_has_read_everything=} {child_wants_input=}")  # <<<
            if child_has_read_everything and child_wants_input:
                to_write = self._input_callback()
                newlines_sent += to_write.count(b"\n")
                assert to_write.endswith(b"\n")
                print(f"Driver writing {to_write} to {manager_fd}")  # <<<
                os.write(manager_fd, to_write)
                # <<< import termios  # <<<
                # <<<
                # <<< termios.tcdrain(manager_fd)  # <<<

        return watcher.exitcode
