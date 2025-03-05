import sys
from textwrap import dedent

from .repl_driver import ReplDriver


class TestReplDriver:
    def test_cat(self):
        """
        >>> explain <<<
        """
        inputs = [
            "foo\n",
            "\n",
            "bar\n",
            "\x04",  # ASCII "end of transmission"
        ]
        output = bytearray()
        driver = ReplDriver(
            args=["cat"],
            input_callback=lambda: inputs.pop(0).encode(),
            on_output=output.extend,
        )

        driver.spawn()

        assert len(inputs) == 0
        actual = output.decode().replace("\r\n", "\n")
        expected = dedent(
            """\
            foo
            foo


            bar
            bar
            """
        )
        assert actual == expected

    def test_python(self):
        """
        Python uses readline and select to check if stdin
        is readable before trying to read() it.
        """
        inputs = [
            "def doit():\n",
            "  return 1 + 1\n",
            "\n",
            "doit()\n",
            "quit()\n",
        ]
        output = bytearray()
        driver = ReplDriver(
            args=[sys.executable, "-q"],
            input_callback=lambda: inputs.pop(0).encode(),
            on_output=output.extend,
        )

        driver.spawn()

        assert len(inputs) == 0
        actual = output.decode().replace("\r\n", "\n")
        expected = dedent(
            """\
            >>> def doit():
            ...   return 1 + 1
            ... 
            >>> doit()
            2
            >>> quit()
            """
        )
        assert actual == expected
