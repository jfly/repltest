# Exiting

By default, `repltest` ignores the exit code of your entrypoint (other than
waiting to make sure that it *does* exit, see [./timeouts.md](./timeouts.md)).

Why?

1. This is consistent with `repltest`'s visual-first design: it's all about
   asserting what users can see, and users can't really see the exit code of a cli
   program (unless you run that program inside of a shell session and check the
   exit code explicitly, which you can totally do with `repltest`!)
2. Many REPLs exit nonzero when they receive a SIGHUP (which gets sent to
   any processes still running at the end of a `repltest` session).

That said, if you want `repltest` to check the exit code of your entrypoints,
you can opt into this behavior with `--check-exit-code`.

## "Natural" exits

Here's a Python shell session that "naturally" exits nonzero:

`natural-exit-42.transcript`:

```console test-file="natural-exit-42.transcript"
>>> import os
>>> os._exit(42)
Some bogus output here to demonstrate that `repltest` still
verifies the session even if the entrypoint exits nonzero.
```

Note how `repltest` notices both the mismatch in the session, and complains that
the entrypoint exited nonzero:

```console test-entrypoint="sh"
$ repltest --entrypoint="python -q" natural-exit-42.transcript --check-exit-code
Error: 'python -q' exited with nonzero exit code: 42
Found a discrepancy. See diff below:
+------------------------- Expected ------------------------+    +-------------------------- Actual -------------------------+
|>>> import os                                              |    |>>> import os                                              |
|>>> os._exit(42)                                           |    |>>> os._exit(42)                                           |
|Some bogus output here to demonstrate that `repltest` still|    |█                                                          |
 ---- ----- ------ ---- -- ----------- ---- ---------- -----       +++ +++++ ++++++ ++++ ++ +++++++++++ ++++ ++++++++++ +++++
|verifies the session even if the entrypoint exits nonzero. |    |                                                           |
 -------- --- ------- ---- -- --- ---------- ----- --------       ++++++++ +++ +++++++ ++++ ++ +++ ++++++++++ +++++ ++++++++
+-----------------------------------------------------------+    +-----------------------------------------------------------+
Final state of screen:
+-----------------------------------------------------------+
|>>> import os                                              |
|>>> os._exit(42)                                           |
|█                                                          |
|                                                           |
+-----------------------------------------------------------+
$ echo $?
1
$
```

## Implicit SIGHUP

If your entrypoint hasn't exited by the end of the session, it will recieve a
`SIGHUP` when `repltest` closes the psuedoterminal (PTY).

`pyhup.transcript`:

```console test-file="pyhup.transcript"
>>> import signal, os
>>> def handle_hup(signum, frame):
...     os._exit(int(os.environ["EXIT_CODE_ON_HUP"]))
...
>>> signal.signal(signal.SIGHUP, handle_hup)
<Handlers.SIG_DFL: 0>
>>>
```

Here's an example of SIGHUP resulting in a clean exit code:

```console test-entrypoint="sh"
$ EXIT_CODE_ON_HUP=0 repltest --entrypoint="python -q" pyhup.transcript --check-exit-code
Success! The test session matched the transcript.
$
```

And here's an example of SIGHUP resulting in a nonzero exit code:

```console test-entrypoint="sh"
$ EXIT_CODE_ON_HUP=42 repltest --entrypoint="python -q" pyhup.transcript --check-exit-code
Error: 'python -q' exited with nonzero exit code: 42
Final state of screen:
+-----------------------------------------------------+
|>>> import signal, os                                |
|>>> def handle_hup(signum, frame):                   |
|...     os._exit(int(os.environ["EXIT_CODE_ON_HUP"]))|
|...                                                  |
|>>> signal.signal(signal.SIGHUP, handle_hup)         |
|<Handlers.SIG_DFL: 0>                                |
|>>> █                                                |
+-----------------------------------------------------+
$ echo $?
1
$
```

## Cleanup

If your entrypoint doesn't exit "naturally" or after SIGHUP, `repltest` will
escalate to more extreme cleanup measures. See [timeouts.md](./timeouts.md) for
details.
