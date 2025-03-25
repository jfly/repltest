import dataclasses
import os
import re
import shlex
import subprocess
import tempfile
from pathlib import Path

import _pytest.fixtures
import pytest

MD_EXAMPLES = [
    Path("README.md"),
    *Path("examples").glob("*.md"),
]


@pytest.fixture(params=MD_EXAMPLES, ids=[str(e) for e in MD_EXAMPLES])
def md_example(request: _pytest.fixtures.SubRequest):
    return request.param


@dataclasses.dataclass
class ExampleFile:
    name: str
    contents: str


@dataclasses.dataclass
class Example:
    files: list[ExampleFile]
    entrypoint: list[str]
    transcript: str


@dataclasses.dataclass
class Codeblock:
    prefix: str
    backticks: str
    info: dict[str, str]
    contents: str


FENCE_RE = re.compile("^(?P<prefix> *)(?P<backticks>```+)(?P<info>.*)$")


def parse_markdown(md: Path) -> list[Codeblock]:
    codeblocks = []

    current_codeblock = None
    with md.open("r") as f:
        for line in f:
            if match := FENCE_RE.match(line):
                prefix = match.group("prefix")
                backticks = match.group("backticks")
                if current_codeblock is not None:
                    if backticks == current_codeblock.backticks:
                        current_codeblock.contents += prefix[
                            len(current_codeblock.prefix) :
                        ]
                        codeblocks.append(current_codeblock)
                        current_codeblock = None
                else:
                    info_kvs = [
                        kv.split("=", 1) if "=" in kv else [kv, ""]
                        for kv in shlex.split(match.group("info"))
                    ]
                    current_codeblock = Codeblock(
                        prefix=prefix,
                        backticks=backticks,
                        info={k: v for k, v in info_kvs},
                        contents="",
                    )
            elif current_codeblock is not None:
                current_codeblock.contents += line[len(current_codeblock.prefix) :]

    return codeblocks


def codeblocks_to_examples(codeblocks: list[Codeblock]) -> list[Example]:
    examples = []

    example_files = []
    for codeblock in codeblocks:
        if test_filename := codeblock.info.get("test-file"):
            example_files.append(
                ExampleFile(
                    name=test_filename,
                    contents=codeblock.contents,
                )
            )

        if test_entrypoint := codeblock.info.get("test-entrypoint"):
            entrypoint = shlex.split(test_entrypoint)
            examples.append(
                Example(
                    files=list(example_files),
                    entrypoint=entrypoint,
                    transcript=codeblock.contents,
                )
            )

    return examples


def test_example(md_example: Path):
    codeblocks = parse_markdown(md_example)
    examples = codeblocks_to_examples(codeblocks)

    for example in examples:
        with tempfile.TemporaryDirectory() as tmp:
            tmp = Path(tmp)

            # Store transcript in a file, so we can test it.
            transcript_file = tmp / "transcript.txt"
            transcript_file.write_text(example.transcript)

            # Create directory to run in.
            session_dir = tmp / "session.tmp"
            for file in example.files:
                p = session_dir / file.name
                p.parent.mkdir(parents=True, exist_ok=True)
                p.write_text(file.contents)

            subprocess.run(
                [
                    "repltest",
                    "--entrypoint",
                    *example.entrypoint,
                    transcript_file,
                ],
                cwd=session_dir,
                check=True,
                text=True,
                env={
                    **os.environ,
                    "PS1": "$ ",
                    # Workaround for https://github.com/python/cpython/issues/131743
                    "PYTHON_BASIC_REPL": "1",
                },
            )
