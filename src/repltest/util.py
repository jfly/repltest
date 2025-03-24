import logging
import termios

logger = logging.getLogger(__name__)


def get_special_char_vals(tty: int) -> set[int]:
    # From `help(termios.tcgetattr)`:
    # > cc is a list of the tty special characters (each a string of
    # > length 1, except the items with indices VMIN and VTIME, which are
    # > integers when these fields are defined
    cc: list[bytes | int]
    _iflag, _oflag, _cflag, _lflag, _ispeed, _ospeed, cc = termios.tcgetattr(tty)
    return set(ord(c) for c in cc if not isinstance(c, int))
