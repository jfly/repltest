import datetime as dt
import re

import click


class TimedeltaType(click.ParamType):
    name = "duration"

    def convert(self, value: str | dt.timedelta, param, ctx) -> dt.timedelta:
        if isinstance(value, dt.timedelta):
            return value

        dt.timedelta()
        match = re.fullmatch(r"(?P<value>.*?)(?P<unit>[a-zA-Z]*)", value)
        assert match is not None

        value_str, unit_suffix = match.groups()

        try:
            count = float(value_str)
        except ValueError:
            count = None

        unit = {
            "us": "microseconds",
            "ms": "milliseconds",
            "s": "seconds",
            "m": "minutes",
            "h": "hours",
            "d": "days",
            "w": "weeks",
        }.get(unit_suffix)

        if count is None or unit is None:
            invalid_reasons = []
            if count is None:
                invalid_reasons.append(f"bad count: {value_str!r}")

            if unit is None:
                invalid_reasons.append(f"bad unit: {unit_suffix!r}")

            reasons = ", ".join(invalid_reasons)
            self.fail(f"{value!r} is not a valid time delta: {reasons}", param, ctx)

        return dt.timedelta(**{unit: count})


TIMEDELTA = TimedeltaType()
