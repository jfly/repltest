# `repltest`

`repltest` is a tool for verifying that REPL transcripts do what they say they do.

## Demo

If you want to drive a REPL with a tool like `pexpect`, you have to carefully
craft regexes that identify when the program is waiting for user input.
Depending on what you're driving, this is somewhere between annoying to
impossible. For example, consider this shell transcript:

`transcript.txt`:

```console test-file="transcript.txt"
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

`repltest` can handle this with very little configuration. It just needs an
entrypoint and a transcript:

```console test-entrypoint=sh
$ repltest --entrypoint=sh transcript.txt
Success! The test session matched the transcript.
$
```

## Docs

In addition to this `README`, take a look through the [examples](./examples/).

## How it works

`repltest` only works with REPLs that follow these rules:

1. There is a non-zero width prompt whenever a user is expected to enter a command.

   Multiline input is OK, but there still must be a prompt, even if it's all
   whitespace.

   ✅ For example, this is OK:

   ```console
   $ nix repl --quiet
   nix-repl> a =
             42

   nix-repl>
   ```

   There are 4 prompts in the above transcript:

   1. `$ `
   2. `nix-repl> `
   4. `          ` (10 spaces)
   4. `nix-repl> `

   ❌ But this is not OK:

   ```console
   $ python -c 'print(input())'
   hello, world
   hello, world
   ```

   The `$ ` prompt is fine, but then `python` blocks on user input without any
   prompt.
2. The REPL disables [TTY
   `ECHO`](https://www.gnu.org/software/libc/manual/html_node/Local-Modes.html#index-ECHO)
   when prompting the user, and re-enables `ECHO` when executing a command.
   - This is normal for REPLs that provide features like history and tab
     completion. For example, anything using the [`readline` library](https://tiswww.cwru.edu/php/chet/readline/rltop.html).
   - Very simple programs that just `read(STDIN_FILENO)` probably leave `ECHO`
     enabled, and won't work with `repltest`. If you run into such a REPL,
     consider adding `readline` support to it!

## Prior art

This project is *heavily* inspired by
[tesh](https://github.com/OceanSprint/tesh). I wanted to explore an
implementation with slightly different design goals:

1. Don't require the user to configure prompt regexes.
2. Render output with a proper VTXXX terminal emulator.
   I didn't want to write any [regexes to strip ANSI escape
   sequences](https://github.com/OceanSprint/tesh/blob/0.3.2/src/tesh/test.py#L18-L19).
   Striping ANSI escape sequences works well for simple things like color, but
   quickly falls apart once you're dealing with a REPL that moves the cursor around
   the screen using CSI sequences or `\r`.
3. Be truly REPL agnostic. AKA: no knowledge of shell semantics [like
   this](https://github.com/OceanSprint/tesh/blob/0.3.2/src/tesh/test.py#L124-L125).
