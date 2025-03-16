import argparse
import logging
import sys

from repl_driver import ReplDriver


def demo():
    inputs = [
        "def query():\n",
        'return input("Favorite color? ")\n',
        "\n",
        "query()\n",
        "red\n",
        "\x04",  # EOT: end of transmission
    ]

    def on_output(out: bytes):
        sys.stdout.buffer.write(out)
        sys.stdout.flush()

    driver = ReplDriver(
        args=["python"],
        on_output=on_output,
        input_callback=lambda: inputs.pop(0).encode(),
    )
    driver.check_returncode()


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("-v", "--verbose", action="store_true")

    args = parser.parse_args()

    log_level = logging.DEBUG if args.verbose else logging.INFO
    logging.basicConfig(level=log_level)

    demo()


if __name__ == "__main__":
    main()
