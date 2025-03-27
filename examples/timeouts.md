# Timeouts

`repltest` supports 3 types of timeouts:

- `--timeout`: How long the test session is allowed to execute for.
- `--cleanup-term-after`: When cleaning up after a test session, how long to
  wait after SIGHUP before sending a SIGTERM to the child process.
- `--cleanup-kill-after`: How long to wait after SIGTERM before
  sending a SIGKILL to the child process.

## Session Timeout

Use `--timeout` to ensure test sessions don't run forever.

`long-sleep.transcript`:

```console test-file="long-sleep.transcript"
$ sleep 5
```

Note how the test quickly fails:

```console test-entrypoint=sh
$ COVERAGE_DEBUG=trace COVERAGE_DEBUG_FILE=/tmp/cov.out repltest --entrypoint="sh" long-sleep.transcript --timeout=0.1s
Error: session timed out
Final state of screen:
+---------+
|$ sleep 5|
|█        |
+---------+
$
```

## Cleanup Timeouts

If your entrypoint doesn't exit by the end of the session (see
[exiting.md](./exiting.md) for details), then you can configure `repltest` to
escalate to a `SIGTERM` and finally a `SIGKILL`.

This session ignores `SIGHUP`, but will die after a `SIGTERM`:

`sigterm.transcript`:

```console test-file="sigterm.transcript"
$ trap "" SIGHUP; \
> trap "exit" SIGTERM; \
> while true; do \
>     sleep 1; \
> done

```

Note how `repltest` informs you about the `SIGTERM` that was necessary to stop
the process.

```console test-entrypoint=sh
$ repltest --entrypoint="sh" sigterm.transcript --timeout=0.5s --cleanup-term-after=0.5s
WARNING:repltest.spawn:Timed out waiting for process to exit. Sending SIGTERM.
Error: session timed out
Final state of screen:
+------------------------+
|$ trap "" SIGHUP; \     |
|> trap "exit" SIGTERM; \|
|> while true; do \      |
|>     sleep 1; \        |
|> done                  |
|█                       |
+------------------------+
$
```

This session ignores `SIGHUP` and `SIGTERM`, but like all mortals, will succumb
to a `SIGKILL`.

`sigterm.transcript`:

```console test-file="sigterm.transcript"
$ trap "" SIGHUP; \
> trap "" SIGTERM; \
> while true; do \
>     sleep 1; \
> done

```

Note how `repltest` informs you about the `SIGKILL` that was necessary to stop
the process.

```console test-entrypoint=sh
$ repltest --entrypoint="sh" sigterm.transcript --timeout=0.5s --cleanup-term-after=0s --cleanup-kill-after=0s
WARNING:repltest.spawn:Timed out waiting for process to exit. Sending SIGTERM.
WARNING:repltest.spawn:Timed out waiting for process to exit. Sending SIGKILL.
Error: session timed out
Final state of screen:
+--------------------+
|$ trap "" SIGHUP; \ |
|> trap "" SIGTERM; \|
|> while true; do \  |
|>     sleep 1; \    |
|> done              |
|█                   |
+--------------------+
$
```
