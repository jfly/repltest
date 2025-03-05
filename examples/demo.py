import sys

from repl_driver import ReplDriver

inputs = [
    "python -q\n",
    "def query():\n",
    '  return input("Favorite color? ")\n',
    "\n",
    "query()\n",
    "red\n",
    "quit()\n",
    'echo -n "$ " && sleep 1 && echo\n',
    "exit\n",
]


def on_output(out: bytes):
    sys.stdout.buffer.write(out)
    sys.stdout.flush()


driver = ReplDriver(
    args=["sh"],
    on_output=on_output,
    input_callback=lambda: inputs.pop(0).encode(),
)
driver.spawn()
