import datetime as dt
import enum
import logging
import shlex
from dataclasses import dataclass
from pathlib import Path

import click
import pyte

from repltest.exceptions import ReplTimeoutException

from .display import Display
from .repl_driver import ReplDriver
from .timedelta_cli_type import TIMEDELTA


class Transcript:
    def __init__(self, transcript: str):
        assert len(transcript) > 1, "Transcript must be non-empty"
        self._transcript_lines = transcript.splitlines()
        self.width = max(len(line) for line in self._transcript_lines)
        self.height = len(self._transcript_lines)
        self._last_coord_in_transcript = (
            self.height - 1,
            len(self._transcript_lines[-1]),
        )

    def char_at(self, line: int, column: int) -> str | None:
        """
        Get the character at the given `(line, column)`.
        This is based on what the user should see: lines
        that are shorter than the width of the terminal
        are treated as implicitly ending with whitespace.

        However, if the requested `(line, column)` is past
        the end of the transcript, then we return `None` so
        calling code can know it's time to end the session.
        """
        assert 0 <= line, "line must be >= 0"
        assert 0 <= column < self.width, f"column must be in bounds [0, {self.width})"

        # Return `None` if the request is past the end of the transcript.
        if (line, column) > self._last_coord_in_transcript:
            return None

        transcript_line = self._transcript_lines[line]
        ch = transcript_line[column] if column < len(transcript_line) else " "
        return ch


class Check(enum.Enum):
    UNTIL_CURSOR = enum.auto()
    FULL_SCREEN = enum.auto()


def identify_mismatch(
    transcript: Transcript, screen: pyte.Screen, check: Check
) -> str | None:
    assert transcript.width == screen.columns
    width = transcript.width
    height = max(transcript.height, screen.lines)

    expected_display = Display(
        title="Expected",
        width=width,
        height=height,
    )
    actual_display = Display(title="Actual", width=width, height=height)

    found_mismatch = False

    for y in range(actual_display.height):
        for x in range(actual_display.width):
            expected_char = transcript.char_at(column=x, line=y) or " "
            actual_char = screen.buffer[y][x].data

            expected_display[y][x] = expected_char
            actual_display[y][x] = actual_char

            match check:
                case Check.UNTIL_CURSOR:
                    should_check = (y, x) < (screen.cursor.y, screen.cursor.x)
                case Check.FULL_SCREEN:
                    should_check = True
                case _:  # pragma: no cover
                    assert False, f"Unrecognized check method: {check}"

            if should_check and expected_char != actual_char:
                found_mismatch = True
                expected_display[y][x].add_annotation("-")
                actual_display[y][x].add_annotation("+")

    # Add the cursor.
    actual_display[screen.cursor.y][screen.cursor.x] = "█"

    if not found_mismatch:
        return None

    side_by_side = []
    for left_line, right_line in zip(
        expected_display.rendered_lines(),
        actual_display.rendered_lines(),
    ):
        side_by_side.append(f"{left_line}    {right_line}")

    return "\n".join(side_by_side)


@dataclass
class VerifyResult:
    issues: list[str]
    final_screen: pyte.Screen


class MismatchException(Exception):
    def __init__(self, mismatch_info: str):
        self.mismatch_info = mismatch_info


def verify_transcript(
    entrypoint: str,
    transcript: Transcript,
    check_exit_code: bool,
    timeout: dt.timedelta | None,
    cleanup_term_after: dt.timedelta | None,
    cleanup_kill_after: dt.timedelta | None,
) -> VerifyResult:
    def handle_input(screen: pyte.Screen, prompt: str) -> bytes | None:
        # Verify the transcript matches the screen up to
        # (but not including) the cursor.
        if mismatch_info := identify_mismatch(
            transcript, screen, check=Check.UNTIL_CURSOR
        ):
            raise MismatchException(mismatch_info)

        # Ok, the transcript matches so far!
        # Now lets get the rest of the current line in the
        # transcript (from the cursor to the end of the line).
        # That's what we'll send as input.
        chars = [
            transcript.char_at(line=screen.cursor.y, column=x)
            for x in range(screen.cursor.x, transcript.width)
        ]
        non_null_chars = [ch for ch in chars if ch is not None]

        # We've reached the end of the transcript, kill the session.
        if len(non_null_chars) == 0:
            return None

        rest_of_line = "".join(non_null_chars)
        # The command likely doesn't perfectly fill the screen.
        # Remove any trailing whitespace.
        rest_of_line = rest_of_line.rstrip()
        return (rest_of_line + "\n").encode()

    def handle_output(screen: pyte.Screen, output: bytes):
        pass

    repl_driver = ReplDriver(
        entrypoint=shlex.split(entrypoint),
        columns=transcript.width,
        lines=transcript.height,
        input_callback=handle_input,
        on_output=handle_output,
        timeout=timeout,
        cleanup_term_after=cleanup_term_after,
        cleanup_kill_after=cleanup_kill_after,
        check_nonzero_exit_code=False,  # We handle this explicitly.
    )

    issues = []

    mismatch_info = None
    try:
        repl_driver.drive()
    except MismatchException as e:
        # Hit a mismatch partway through.
        mismatch_info = e.mismatch_info
    except ReplTimeoutException:
        issues.append("session timed out")
    else:
        # At the very end do a final comparison against the transcript.
        mismatch_info = identify_mismatch(
            transcript,
            repl_driver.screen,
            # At the end, it doesn't matter where the cursor is, we need the
            # transcript to fully match the screen.
            check=Check.FULL_SCREEN,
        )

    assert repl_driver.exit_code is not None
    if check_exit_code and repl_driver.exit_code != 0:
        issues.append(
            f"{entrypoint!r} exited with nonzero exit code: {repl_driver.exit_code}"
        )

    if mismatch_info is not None:
        issues.append(f"Found a discrepancy. See diff below:\n{mismatch_info}")

    return VerifyResult(issues=issues, final_screen=repl_driver.screen)


@click.command()
@click.option("-v", "--verbose", count=True)
@click.option("--entrypoint", required=True)
@click.option("--check-exit-code/--no-check-exit-code", default=False)
@click.option(
    "--timeout",
    type=TIMEDELTA,
    help="How long the test session is allowed to execute for.",
)
@click.option(
    "--cleanup-term-after",
    type=TIMEDELTA,
    help="When cleaning up after a test session, how long to wait after SIGHUP before sending a SIGTERM to the child process.",
)
@click.option(
    "--cleanup-kill-after",
    type=TIMEDELTA,
    help="When cleaning up after a test session, how long to wait after SIGTERM before sending a SIGKILL to the child process.",
)
@click.argument("transcript", type=click.Path(exists=True, path_type=Path))
def main(
    entrypoint: str,
    transcript: Path,
    verbose: int,
    check_exit_code: bool,
    timeout: dt.timedelta | None,
    cleanup_term_after: dt.timedelta | None,
    cleanup_kill_after: dt.timedelta | None,
):
    """
    Verify that the given TRANSCRIPT (a file) can be reproduced with
    the given ENTRYPOINT.
    """
    log_level = logging.WARNING
    log_level -= 10 * verbose
    logging.basicConfig(level=log_level)

    result = verify_transcript(
        entrypoint=entrypoint,
        transcript=Transcript(transcript.read_text()),
        check_exit_code=check_exit_code,
        timeout=timeout,
        cleanup_term_after=cleanup_term_after,
        cleanup_kill_after=cleanup_kill_after,
    )

    if len(result.issues) > 0:
        raise click.ClickException(
            "\n".join(result.issues)
            + "\nFinal state of screen:\n"
            + str(Display.from_pyte_screen(result.final_screen))
        )

    print("Success! The test session matched the transcript.")
