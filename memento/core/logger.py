"""Structured logging.

Every line Memento writes to a terminal or its log file follows one format:

    CODE_AREA_STATUS ,{json data}

so output is greppable and machine-parseable. Use `emit()` for stdout and
`line()` when you need the string (e.g. to also append it to a log file).
"""

from __future__ import annotations

import json
from typing import Any


def line(code: str, **data: Any) -> str:
    return "{} ,{}".format(code, json.dumps(data, default=str, separators=(",", ":")))


def emit(code: str, **data: Any) -> None:
    print(line(code, **data))
