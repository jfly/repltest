from .analyze_syscall import ReadSyscall


def test_str():
    syscall = ReadSyscall(pid=42, syscall_args=[1, 2, 1024])
    assert "read(1, 2, 1024)" == str(syscall)
