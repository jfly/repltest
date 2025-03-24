import argparse
import logging
import os
import sys

from repltest import drive_repl


def demo():
    inputs = [
        "python -q\n",
        "def query():\n",
        'return input("Favorite color? ")\n',
        "\n",
        "query()\n",
        "red\n",
        "quit()\n",
        'echo -n "$ " && sleep 1 && echo\n',
        "\x04",  # EOT: end of transmission
    ]

    def on_output(out: bytes):
        sys.stdout.buffer.write(out)
        sys.stdout.flush()

    drive_repl(
        args=["sh"],
        env={**os.environ, "PS1": "$ "},
        on_output=on_output,
        input_callback=lambda: inputs.pop(0).encode(),
    )


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("-v", "--verbose", action="store_true")

    args = parser.parse_args()

    log_level = logging.DEBUG if args.verbose else logging.INFO
    logging.basicConfig(level=log_level)

    demo()


if __name__ == "__main__":
    main()
