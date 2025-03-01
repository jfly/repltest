#include <stdio.h>
#include <stdlib.h>
#include <unistd.h>

int main() {
  const char *prompt = "prompt> ";

  ssize_t BUF_SIZE = 1024;
  char buf[BUF_SIZE];

  while (1) {
    printf("%s", prompt);
    fflush(stdout);
    int count = read(0, buf, BUF_SIZE);
    if (count == 0) {
      fprintf(stderr, "ERROR: Could not read from stdin. Aborting.\n");
      exit(1);
    }
    puts(buf);
  }

  return 0;
}
