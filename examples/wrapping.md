# Line Wrapping

`repltest` automatically deduces the width and height of the screen from the
transcript.

`transcript.txt`:

```console test-file="transcript.txt"
$ python -c "print('*'*80)"
****************************************
****************************************
$
```

Verify it works:

```console test-entrypoint=sh
$ repltest --entrypoint=sh transcript.txt
Success! The test session matched the transcript.
$
```
