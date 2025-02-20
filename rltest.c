#include <readline/history.h>
#include <readline/readline.h>
#include <stdio.h>
#include <stdlib.h> /* for free() */
#include <unistd.h> /* for usleep() */

char running = 1;

// The function that'll get passed each line of input
void my_rlhandler(char *line) {
  if (line == NULL) {
    // Ctrl-D will allow us to exit nicely
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

// The main entry-point for the program
int main() {
  const char *prompt = "WOOP> ";

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
