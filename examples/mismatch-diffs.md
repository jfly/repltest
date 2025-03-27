# Mismatch Diffs

When a transcript doesn't match, `repltest` prints a two-way diff between the
transcript and the session's screen.

`transcript.txt`:

```console test-file="transcript.txt"
>>> print("!\n"*5)
!
```

Note how the diff shows the missing 4 exclamation marks:

```console test-entrypoint=sh
$ repltest --entrypoint="python -q" transcript.txt
Error: Found a discrepancy. See diff below:    
+---- Expected ----+    +----- Actual -----+   
|>>> print("!\n"*5)|    |>>> print("!\n"*5)|   
|!                 |    |!                 |   
|                  |    |!                 |   
 -                       +                     
|                  |    |!                 |   
 -                       +                     
|                  |    |!                 |   
 -                       +                     
|                  |    |!                 |   
 -                       +                     
|                  |    |                  |   
|                  |    |>>> █             |   
 ---                     +++                   
+------------------+    +------------------+
Final state of screen:
+------------------+
|>>> print("!\n"*5)|
|!                 |
|!                 |
|!                 |
|!                 |
|!                 |
|                  |
|>>> █             |
+------------------+
$ echo $?
1
$
```
