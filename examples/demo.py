import logging
import sys

from repl_driver import ReplDriver

log_level = logging.DEBUG
# <<< log_level = logging.INFO
logging.basicConfig(level=log_level)

inputs = [
    "def query():\n",
    'return input("Favorite color? ")\n',
    "\n",
    "query()\n",
    "red\n",
    "\x04",  # EOT: end of transmission
]


def on_output(out: bytes):
    if log_level <= logging.DEBUG:
        return

    sys.stdout.buffer.write(out)
    sys.stdout.flush()


driver = ReplDriver(
    # <<< args=["python"],
    args=["test-repl-read-cooked"],
    on_output=on_output,
    input_callback=lambda: inputs.pop(0).encode(),
)
driver.check_returncode()
