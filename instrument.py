#!/usr/bin/env python

from ptrace.debugger import NewProcessEvent, ProcessSignal, PtraceDebugger, ProcessExit, PtraceProcess
from ptrace.debugger.process import SyscallState
from ptrace.debugger.child import createChild
from ptrace.func_call import FunctionCallOptions
from logging import error
from ptrace.syscall import PtraceSyscall, SyscallArgument
import sys

from ptrace.tools import signal_to_exitcode


class SyscallTracer:
    def __init__(self):
        self._syscall_dispatch = {
            "read": self.handle_read,
        }

    def handle_syscall(self, syscall: PtraceSyscall):
        self._syscall_dispatch[syscall.name](syscall)

    def handle_read(self, syscall: PtraceSyscall):
        assert syscall.name == "read"

        fd_arg: SyscallArgument = syscall.arguments[0]
        buf_arg: SyscallArgument = syscall.arguments[1]
        count_arg: SyscallArgument = syscall.arguments[2]

        # TODO: handle scenario where stdin is not a TTY
        if fd_arg.value != 0:
            return

        if syscall.result is not None:
            buf_contents: bytes
            truncated: bool
            buf_contents, truncated = syscall.process.readCString(buf_arg.value, count_arg.value)
            assert not truncated
            print(f" yo: {buf_contents}") #<<<

    def syscall_trace(self, process: PtraceProcess):
        process.syscall()

        exitcode = 0
        while True:
            # No more processes? Exit
            if len(self.debugger.list) == 0:
                break

            # Wait until next syscall enter
            try:
                event = self.debugger.waitSyscall()
            except ProcessExit as event:
                error("*** %s ***" % event)
                if event.exitcode is not None:
                    exitcode = event.exitcode
                continue
            except ProcessSignal as event:
                event.display()
                event.process.syscall(event.signum)
                exitcode = signal_to_exitcode(event.signum)
                continue
            except NewProcessEvent as event:
                process = event.process
                process.syscall_state.ignore_callback = self.ignore_syscall # type: ignore # urg
                error("*** New process %s ***" % process.pid)
                process.syscall()
                assert process.parent is not None
                process.parent.syscall()
                continue

            # Process syscall enter or exit
            assert event is not None
            self.syscall(event.process)
        return exitcode

    def syscall(self, process: PtraceProcess):
        state: SyscallState = process.syscall_state
        
        syscall_options = FunctionCallOptions()

        syscall = state.event(syscall_options)
        if syscall is not None:
            self.handle_syscall(syscall)

        # Break at next syscall
        process.syscall()

    @staticmethod
    def ignore_syscall(syscall: PtraceSyscall):
        return syscall.name not in ['read']

    def main(self, args: list[str]):
        self.debugger = PtraceDebugger()
        self.debugger.traceFork()

        pid = createChild(args, no_stdout=False, env=None)
        process = self.debugger.addProcess(pid, is_attached=True)
        process.syscall_state.ignore_callback = self.ignore_syscall # type: ignore # urg
        exitcode = self.syscall_trace(process)
        self.debugger.quit()

        sys.exit(exitcode)


if __name__ == "__main__":
    if len(sys.argv) == 1:
        error("You must give me a command to run")
        sys.exit(1)
    SyscallTracer().main(args=sys.argv[1:])
