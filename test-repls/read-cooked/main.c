#include <stdbool.h>
#include <stdio.h>
#include <stdlib.h>
#include <unistd.h>

ssize_t readline_raw(char *buf, ssize_t b_bytes) {
  ssize_t read_bytes = 0;

  while (true) {
    ssize_t max_length = b_bytes - read_bytes - 1;
    if (max_length <= 0) {
      fprintf(stderr,
              "Input line too long. Max bytes (including the newline): %zd",
              b_bytes);
      exit(1);
    }
    ssize_t count = read(STDIN_FILENO, buf + read_bytes, max_length);
    if (count == -1) {
      fputs("Error reading from stdin", stderr);
      exit(1);
    } else if (count == 0) {
      // We just read nothing. Likely because the user sent EOT.
      if (read_bytes == 0) {
        // If we haven't read anything yet, return "".
        return 0;
      } else {
        // If we have read something, then ignore and keep reading until we get
        // a full line. (This behavior is inspired by how the Python REPL
        // works).
        continue;
      }
    }

    read_bytes += count;
    buf[read_bytes] = 0;

    if (buf[read_bytes - 1] == '\n') {
      // We found a newline! Return the string.
      return read_bytes;
    }
  }
}

int main() {
  const char *prompt = "prompt> ";

  char buf[1024];

  while (1) {
    printf("%s", prompt);
    fflush(stdout);

    ssize_t count = readline_raw(buf, sizeof(buf));
    if (count == 0) {
      puts("\nBye!");
      exit(0);
    }

    fputs(buf, stdout);
  }

  return 0;
}
