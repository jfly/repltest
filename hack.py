import os
import pty
import struct
import termios
from fcntl import ioctl

from remote_pdb import RemotePdb


def queue_size(tty: int) -> int:
    (size,) = struct.unpack("i", ioctl(tty, termios.TIOCINQ, b"\0\0\0\0"))
    return size


def is_canonical(tty: int) -> bool:
    iflag, _oflag, _cflag, _lflag, _ispeed, _ospeed, _cc = termios.tcgetattr(tty)
    return (iflag & termios.ICANON) == 1


pid, master_fd = pty.fork()

if pid == 0:
    RemotePdb("127.0.0.1", 4445).set_trace()
else:
    slave_path = os.ptsname(master_fd)
    slave_fd = os.open(slave_path, os.O_RDONLY)
    RemotePdb("127.0.0.1", 4444).set_trace()
