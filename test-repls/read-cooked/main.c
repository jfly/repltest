#include <stdbool.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <unistd.h>

ssize_t readline(char *buf, ssize_t b_bytes) {
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
      // If we haven't read anything yet, return "". If we have, then keep
      // reading until we get a full line. (This behavior is inspired by how the
      // Python REPL works).
      if (read_bytes == 0) {
        return 0;
      } else {
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

    ssize_t count = readline(buf, sizeof(buf));
    if (count == 0) {
      puts("Bye!");
      exit(0);
    }

    write(STDOUT_FILENO, buf, strlen(buf));
  }

  return 0;
}
