# `repl-driver`

`repl-driver` is a Python library for driving REPLs. Think of it like
`pexpect`, but without the waiting or regexes.

## Motivation

If you want to drive a REPL with a tool like `pexpect`, you have to carefully
craft regexes that identify when the program is waiting for user input.
Depending on what you're driving, this is somewhere between annoying to
impossible. For example, consider this shell session:

```console
$ python -q
>>> def query():
...   return input("Favorite color? ")
...
>>> query()
Favorite color? red
'red'
>>> quit()
$ echo -n "$ " && sleep 1 && echo
$
$
```

This is hard to drive traditionally:

1. The prompt keeps changing: `$ `, `>>> `, `... `, and `Favorite color? `
2. There's a moment where the program pauses for a while after printing `$ `.
   This sure looks like a prompt, but it isn't.

You can handle 1) with a clever regex, but 2) requires fiddly logic.

## The big idea

`repl-driver` takes a completely different approach. Rather than trying to
guess when the program is waiting for input, we just check if it is trying to
read from stdin. That allows us to provide a callback API for driving REPLs. No
regexes required!

For example, here's how to reproduce the above shell session with `repl-driver`:

`examples/demo.py`:

```python
import sys
from repl_driver import ReplDriver

inputs = [
    'def query():\n',
    '  return input("Favorite color? ")\n',
    'query()\n',
    "foo()\n",
    "__import__('time').sleep(5); quit()\n",
]

ReplDriver(
    args=["bash"],
    on_output=sys.stdout.write,
    input_callback=lambda: inputs.pop(0).encode(),
)
```

```
$ python examples/demo.py
...
```

## How it works

In short, we achieve this by using `ptrace(2)` to detect if a subprocess is
trying to do a `read(2)` of stdin. The details are a bit messy:

- Some processes use tools like `select` to check if stdin is <<<
- Async <<<
- Portability <<<
