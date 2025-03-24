# `repltest`

`repltest` is a tool for verifying that REPL sessions do what they say they do.

It also includes a Python library (`repltest.Driver`) that can be useful for
programmatically controlling REPLs. Sort of like `pexpect`, but without the
waiting or regexes.

## Motivation

If you want to drive a REPL with a tool like `pexpect`, you have to carefully
craft regexes that identify when the program is waiting for user input.
Depending on what you're driving, this is somewhere between annoying to
impossible. For example, consider this shell session:

`shell-session.txt`:

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

However, `repltest` can handle this with no configuration:

```console
$ repltest --entrypoint=sh shell-session.txt
<<<
```

# How it works

`repltest` only works with REPLs that follow these rules:

1. There is a non-zero width prompt whenever a user is expected to enter a command.
  - Multiline input is OK, but there still must be a prompt, even if it's all
    whitespace.

    For example, this is OK:

    ```console
    $ nix repl --quiet
    nix-repl> a =
              42

    nix-repl>
    ```

    There are 3 prompts in the above session:

    1. `nix-repl> `
    2. `          `
    3. `nix-repl> `

    But this is not OK (there is no prompt):

    ```console
    $ python -c 'print(input())'
    hello, world
    hello, world
    ```
2. The REPL disables TTY `ECHO` when prompting the user, and re-enables `ECHO`
   when executing a command.
  - This is normal for REPLs that provide features like history and tab
    completion. For example, anything using the [`readline` library](https://tiswww.cwru.edu/php/chet/readline/rltop.html).
  - Very simple programs that just `read(STDIN_FILENO)` probably leave `ECHO`
    enabled, and won't work with `repltest`. If you run into such a REPL,
    consider adding `readline` support to it!
