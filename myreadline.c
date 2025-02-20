#include <dlfcn.h>
#include <stdbool.h>
#include <stdio.h>
#include <stdlib.h>

typedef void rl_vcpfunc_t(char *);

bool waiting_for_full_line = false;
rl_vcpfunc_t *unwrapped_handler;

void rl_callback_handler_wrapper(char *line) {
  if (!unwrapped_handler) {
    fprintf(stderr,
            "ERROR: Could not find original `unwrapped_handler` function! "
            "Aborting.\n%s\n",
            dlerror());
    exit(1);
  }

  waiting_for_full_line = false;
  (*unwrapped_handler)(line);

  if (unwrapped_handler != NULL) {
    puts("");
    puts("FEED ME (rl_callback_handler_wrapper)");
    puts("");
    waiting_for_full_line = true;
  }
}

typedef void (*rl_callback_handler_install_func_t)(const char *prompt,
                                                   rl_vcpfunc_t *lhandler);

void rl_callback_handler_install(const char *prompt, rl_vcpfunc_t *lhandler) {
  rl_callback_handler_install_func_t og_install =
      dlsym(RTLD_NEXT, "rl_callback_handler_install");
  if (!og_install) {
    fprintf(stderr,
            "ERROR: Could not find original `rl_callback_handler_install` "
            "function! Aborting.\n%s\n",
            dlerror());
    exit(1);
  }

  if (!waiting_for_full_line) {
    puts("");
    puts("FEED ME (rl_callback_handler_install)");
    puts("");
    waiting_for_full_line = true;
  }

  unwrapped_handler = lhandler;
  og_install(prompt, rl_callback_handler_wrapper);
}

typedef void (*rl_callback_read_char_func_t)(void);

void rl_callback_read_char(void) {
  rl_callback_read_char_func_t og_read_char =
      dlsym(RTLD_NEXT, "rl_callback_read_char");
  if (!og_read_char) {
    fprintf(stderr,
            "ERROR: Could not find original `rl_callback_read_char` function! "
            "Aborting.\n%s\n",
            dlerror());
    exit(1);
  }

  og_read_char();
}

typedef void (*rl_callback_handler_remove_func_t)(void);

void rl_callback_handler_remove(void) {
  rl_callback_handler_remove_func_t og_remove =
      dlsym(RTLD_NEXT, "rl_callback_handler_remove");
  if (!og_remove) {
    fprintf(stderr,
            "ERROR: Could not find original `rl_callback_handler_remove` "
            "function! Aborting.\n%s\n",
            dlerror());
    exit(1);
  }

  waiting_for_full_line = false;
  unwrapped_handler = NULL;
  og_remove();
}
