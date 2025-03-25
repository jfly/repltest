import shlex

__all__ = [
    "ReplTimeoutException",
]


class ReplTimeoutException(Exception):
    pass


class ReplProcessException(Exception):
    def __init__(self, args: list[str], exit_code: int):
        self.cmd_args = args
        self.exit_code = exit_code

    def __str__(self) -> str:
        return f"Command: {shlex.join(self.cmd_args)!r} exited with exit code: {self.exit_code}"
