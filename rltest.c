#include <stdio.h>
#include <stdlib.h>
#include <unistd.h>

// Requires `FILE` from `stdio.h`
#include <readline/history.h>
#include <readline/readline.h>

char running = 1;

void my_rlhandler(char *line) {
  if (line == NULL) {
    printf("\nend of line\n");
    running = 0;
  } else {
    if (*line != 0) {
      // If line wasn't empty, store it so that uparrow retrieves it
      add_history(line);
    }
    printf("Your input was:\n%s\n", line);
    free(line);
  }
}

int main() {
  const char *prompt = "prompt> ";

  // Install the handler
  rl_callback_handler_install(prompt, (rl_vcpfunc_t *)&my_rlhandler);

  // Enter the event loop (simple example, so it doesn't do much except wait)
  running = 1;
  while (running) {
    usleep(10000);
    rl_callback_read_char();
  };
  printf("\nEvent loop has exited\n");

  // Remove the handler
  rl_callback_handler_remove();

  return 0;
}
