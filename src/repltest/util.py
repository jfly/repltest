import datetime as dt
import logging
import termios

import psutil

logger = logging.getLogger(__name__)


def get_special_char_vals(tty: int) -> set[int]:
    # From `help(termios.tcgetattr)`:
    # > cc is a list of the tty special characters (each a string of
    # > length 1, except the items with indices VMIN and VTIME, which are
    # > integers when these fields are defined
    cc: list[bytes | int]
    _iflag, _oflag, _cflag, _lflag, _ispeed, _ospeed, cc = termios.tcgetattr(tty)
    return set(ord(c) for c in cc if not isinstance(c, int))


def graceful_shutdown(
    pid: int, term_after: dt.timedelta, kill_after: dt.timedelta
) -> int:
    """
    Graceful shutdown:

    1. Wait `term_after` for process to exit. If it exits, return the exit code.
    2. Send a SIGTERM.
    3. Wait `kill_after` for process to exit. If it exits, return the exit code.
    4. Send a SIGKILL.
    5. Wait forever for process to exit and return its exit code.
    """
    process = psutil.Process(pid)

    exitcode = None

    try:
        exitcode = process.wait(timeout=term_after.total_seconds())
    except psutil.TimeoutExpired:
        logger.debug("Timed out waiting for %s to exit. Sending SIGTERM", pid)
        process.terminate()

    if exitcode is None:
        try:
            exitcode = process.wait(timeout=kill_after.total_seconds())
        except psutil.TimeoutExpired:
            logger.debug("Timed out waiting for %s to exit. Sending SIGKILL", pid)
            process.kill()

    if exitcode is None:
        exitcode = process.wait()

    logger.debug("Process %s terminated with exit code %s", pid, exitcode)
    return exitcode
