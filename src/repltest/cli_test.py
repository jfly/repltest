from pathlib import Path
from textwrap import dedent

from click.testing import CliRunner

from .cli import main


def test_success(tmp_path: Path):
    transcript = tmp_path / "transcript.txt"
    transcript.write_text(
        dedent(
            """\
            $ echo hiya
            hiya
            $ exit
            exit
            """
        )
    )

    runner = CliRunner()
    result = runner.invoke(
        main,
        ["--entrypoint=sh", str(transcript)],
        env={"PS1": "$ "},
        catch_exceptions=False,
    )
    assert [0, "Success! The test session matched the transcript.\n"] == [
        result.exit_code,
        result.output,
    ]


def test_incomplete_last_command(tmp_path: Path):
    transcript = tmp_path / "transcript.txt"
    transcript.write_text(
        dedent(
            """\
            $ echo hiya
            hiya
            $ exit
            """
        )
    )

    runner = CliRunner()
    result = runner.invoke(
        main,
        ["--entrypoint=sh", str(transcript)],
        env={"PS1": "$ "},
        catch_exceptions=False,
    )
    assert [
        1,
        (
            "Error: Found a discrepancy. See diff below:\n"
            "+- Expected +    +-- Actual -+\n"
            "|$ echo hiya|    |$ echo hiya|\n"
            "|hiya       |    |hiya       |\n"
            "|$ exit     |    |$ exit     |\n"
            "|           |    |exit       |\n"
            " ----             ++++        \n"
            "|           |    |█          |\n"
            "+-----------+    +-----------+\n"
        ),
    ] == [result.exit_code, result.output]


def test_mismatch(tmp_path: Path):
    transcript = tmp_path / "transcript.txt"
    transcript.write_text(
        dedent(
            """\
            $ echo hiya
            this is wrong
            $ exit
            exit
            """
        )
    )

    runner = CliRunner()
    result = runner.invoke(
        main,
        ["--entrypoint=sh", str(transcript)],
        env={"PS1": "$ "},
        catch_exceptions=False,
    )
    assert [
        1,
        (
            "Error: Found a discrepancy. See diff below:\n"
            "+-- Expected -+    +--- Actual --+\n"
            "|$ echo hiya  |    |$ echo hiya  |\n"
            "|this is wrong|    |hiya         |\n"
            " ---- -- -----      ++++ ++ +++++ \n"
            "|$ exit       |    |$ █          |\n"
            "|exit         |    |             |\n"
            "+-------------+    +-------------+\n"
        ),
    ] == [
        result.exit_code,
        result.output,
    ]
