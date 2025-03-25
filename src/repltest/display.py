from collections import defaultdict
from typing import Generator


class DisplayCell:
    def __init__(self, char: str = " "):
        self.char = char
        self.annotation = None

    def add_annotation(self, char: str):
        assert len(char) == 1
        self.annotation = char


class DisplayLine:
    def __init__(self, width: int):
        self.width = width
        self._cells = defaultdict(lambda: DisplayCell())

    def __getitem__(self, column: int) -> DisplayCell:
        return self._cells[column]

    def __setitem__(self, column: int, ch: str):
        assert len(ch) == 1
        assert 0 <= column < self.width

        self._cells[column] = DisplayCell(ch)

    def render(self) -> str:
        return "".join(self[i].char for i in range(self.width))

    def render_annotations(self) -> str | None:
        annotations = [self[i].annotation for i in range(self.width)]
        if all(annotation is None for annotation in annotations):
            return None
        return "".join(annotation or " " for annotation in annotations)


class Display:
    def __init__(self, width: int, height: int, title: str):
        self.width = width
        self.height = height
        self.title = title

        self._lines: dict[int, DisplayLine] = defaultdict(
            lambda: DisplayLine(self.width)
        )

    def _horizontal_border(self, description: str | None, fill: str = "-"):
        maxlen = self.width - 2  # Leave space for whitespace on left and right.
        desc = "" if description is None else (" " + description[:maxlen] + " ")
        return f"+{desc.center(self.width, fill)}+"

    def rendered_lines(self) -> Generator[str, None, None]:
        yield self._horizontal_border(self.title)

        for y in range(self.height):
            line = self[y]
            yield "|" + line.render() + "|"
            annotations = line.render_annotations()
            if annotations:
                yield " " + annotations + " "

        yield self._horizontal_border(None)

    def __getitem__(self, y: int) -> DisplayLine:
        assert 0 <= y <= self.height
        return self._lines[y]
