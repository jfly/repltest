#include <stdbool.h>
#include <stdio.h>
#include <stdlib.h>
#include <unistd.h>

// Requires `FILE` from `stdio.h`
#include <readline/history.h>
#include <readline/readline.h>

char running = 1;

void handle_line(char *line) {
  if (line == NULL) {
    running = 0;
    rl_callback_handler_remove();
  } else {
    puts(line);
    free(line);
  }
}

int main() {
  const char *prompt = "prompt> ";

  rl_callback_handler_install(prompt, (rl_vcpfunc_t *)&handle_line);

  running = 1;
  while (running) {
    usleep(10000);
    rl_callback_read_char();
  };
  puts("Bye!");

  return 0;
}
