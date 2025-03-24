#include <errno.h>
#include <poll.h>
#include <stdbool.h>
#include <stdio.h>
#include <stdlib.h>
#include <sys/poll.h>
#include <sys/select.h>
#include <unistd.h>

// Requires `FILE` from `stdio.h`
#include <readline/history.h>
#include <readline/readline.h>

#define ASSERT_OK(call)                                                        \
  ({                                                                           \
    int _result = call;                                                        \
    if (_result < 0) {                                                         \
      fprintf(stderr, "Error at %s:%d - %s failed: %s (errno: %d)\n",          \
              __FILE__, __LINE__, #call, strerror(errno), errno);              \
      exit(EXIT_FAILURE);                                                      \
    }                                                                          \
    _result; /* Return the result */                                           \
  })

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

void loop_poll() {
  struct pollfd fds[] = {
      {.fd = STDIN_FILENO, .events = POLLRDNORM | POLLRDBAND},
  };
  int nfds = sizeof(fds) / sizeof(struct pollfd);
  int timeout_msecs = -1; // Wait forever.

  running = 1;
  while (running) {
    int ret = ASSERT_OK(poll(fds, nfds, timeout_msecs));

    if (ret > 0) {
      for (int i = 0; i < nfds; i++) {
        if (fds[i].revents & POLLRDNORM || fds[i].revents & POLLRDBAND) {
          rl_callback_read_char();
        }
      }
    }
  };
}

// NOTE: Both `select` and `pselect` (on Linux) appear to be calling the
//       `pselect6` syscall under the hood. I'm not sure if this is a glibc
//       quirk.
void loop_select() {
  int nfds = 1;
  fd_set readfds;

  running = 1;
  while (running) {
    FD_ZERO(&readfds);
    FD_SET(STDIN_FILENO, &readfds);
    int ret = ASSERT_OK(select(nfds, &readfds, NULL, NULL, NULL));

    if (ret > 0) {
      if (FD_ISSET(STDIN_FILENO, &readfds)) {
        rl_callback_read_char();
      }
    }
  };
}

typedef struct {
  char *name;
  void (*loop)(void);
} PollMechanism;

PollMechanism POLL_MECHANISMS[] = {
    {.name = "poll", .loop = &loop_poll},
    {.name = "select", .loop = &loop_select},
};

PollMechanism *find_poll_mechanism(char *requested_mechanism_name) {
  for (int i = 0; i < sizeof(POLL_MECHANISMS) / sizeof(PollMechanism); i++) {
    PollMechanism *mechanism = &POLL_MECHANISMS[i];
    if (strcmp(requested_mechanism_name, mechanism->name) == 0) {
      return mechanism;
    }
  }
  return NULL;
}

void print_help(char *arg0) {
  fprintf(stderr, "Usage: %s [mechanism]\n\n", arg0);
  fprintf(stderr, "Where [mechanism] is one of the following:\n");
  for (ssize_t i = 0; i < sizeof(POLL_MECHANISMS) / sizeof(PollMechanism);
       i++) {
    fprintf(stderr, "  %s\n", POLL_MECHANISMS[i].name);
  }
}

int main(int argc, char **argv) {
  if (argc != 2) {
    fprintf(stderr, "You must specify exactly 1 poll mechanism.\n");
    exit(1);
  }

  char *requested_mechanism = argv[1];

  if (strcmp("--help", requested_mechanism) == 0) {
    print_help(argv[0]);
    exit(0);
  }

  PollMechanism *mechanism = find_poll_mechanism(requested_mechanism);
  if (mechanism == NULL) {
    fprintf(stderr, "No poll mechanism found called %s\n", requested_mechanism);
    exit(1);
  }

  puts("This is a nice");
  puts("... long");
  puts("multiline intro.");

  // Disable bracketed paste: it adds a lot of ANSI
  // escape sequence noise to the output.
  rl_variable_bind("enable-bracketed-paste", "off");

  const char *prompt = "prompt> ";

  rl_callback_handler_install(prompt, (rl_vcpfunc_t *)&handle_line);

  mechanism->loop();

  puts("Bye!");

  return 0;
}
