import os
import pty
import sys
import code
from threading import Thread

def read_tty(master_fd):
    with open("/tmp/foo.log", "wb") as f:
        while True:
            data = os.read(master_fd, 1024)
            f.write(data)
            f.flush()

def drive(child_pid, master_fd):
    t = Thread(target=read_tty, args=[master_fd], daemon=True)
    t.start()

    import readline
    shell = code.InteractiveConsole({
        "child_pid": child_pid,
        "master_fd": master_fd,
    })
    shell.interact()

    os.close(master_fd)
    os.waitpid(child_pid, 0)

def main():
    pid, fd = pty.fork()
    if pid == 0:
        # <<< argv = ["build/rltest"]
        argv = [sys.executable, "-c", 'print(input("$ "))']
        os.execvpe(argv[0], argv, {})
    else:
        drive(pid, fd)

if __name__ == "__main__":
    main()
