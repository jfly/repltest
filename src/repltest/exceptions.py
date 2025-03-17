import shlex

__all__ = [
    "ReplTimeoutException",
]


class ReplTimeoutException(Exception):
    pass


class ReplProcessException(Exception):
    def __init__(self, args: list[str], returncode: int):
        self.cmd_args = args
        self.returncode = returncode

    def __str__(self) -> str:
        return f"Command: {shlex.join(self.cmd_args)!r} exited with returncode: {self.returncode}"
