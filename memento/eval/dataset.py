"""Load a LongMemEval-style dataset.

A dataset is a JSON list of cases with fields:
  question_id, question_type, question, answer,
  haystack_sessions (list of sessions; each = list of {role, content} turns),
  haystack_dates (optional, parallel to sessions).

With no path, the bundled 6-case sample (one per question type) is used so
`memento eval` runs out of the box. For the real benchmark, download
LongMemEval-S and pass --dataset.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict, List, Optional

SAMPLE = Path(__file__).resolve().parent / "fixtures" / "longmemeval_sample.json"


def load_dataset(path: Optional[str] = None) -> List[Dict[str, Any]]:
    src = Path(path) if path else SAMPLE
    data = json.loads(src.read_text())
    if not isinstance(data, list):
        raise ValueError("dataset must be a JSON list of cases")
    return data
