"""All LLM-facing prompts live here, so they're easy to find and tune.

Keeping prompts out of the code paths makes them reviewable as product copy and
lets you A/B them against the eval harness (`memento eval`).
"""

from __future__ import annotations

from typing import Dict, List

# The open-loops agent: find new loops AND close resolved ones in one pass.
OPEN_LOOPS_INSTRUCTIONS = (
    "You maintain a user's OPEN LOOPS — commitments, promises, follow-ups, or "
    "tasks they still need to act on — from a log of their recent computer "
    "activity.\n\n"
    "You are given (1) the CURRENTLY OPEN LOOPS with ids, and (2) RECENT "
    "ACTIVITY (newest first). Do two things:\n"
    "A. FIND new open loops clearly supported by the activity and not already "
    "in the open list.\n"
    "B. CLOSE any currently-open loop that the activity shows was completed or "
    "resolved.\n\n"
    "Return ONLY a JSON object, no prose:\n"
    '{"new_loops":[{"title":"short imperative","detail":"one sentence of '
    'context","source_app":"app"}],"resolved":[{"id":123,"evidence":"why it is '
    'done"}]}\n'
    "Use [] for empty. Never invent items unsupported by the activity.\n"
)


def build_open_loops_prompt(open_items: List[Dict], activity: List[Dict]) -> str:
    """Render the full open-loops prompt from open items + recent activity rows."""
    open_block = "\n".join(
        "  #{}: {}".format(i["id"], i["title"]) for i in open_items
    ) or "  (none)"
    log = "\n".join(
        "- [{}] {}".format(r["app"], (r["content"] or "").replace("\n", " ")[:200])
        for r in activity
    )
    return "{}\nCURRENTLY OPEN LOOPS:\n{}\n\nRECENT ACTIVITY:\n{}\n".format(
        OPEN_LOOPS_INSTRUCTIONS, open_block, log)


# ---- eval harness (LongMemEval-style QA + LLM judge) ----

QA_INSTRUCTIONS = (
    "Answer the question using ONLY the retrieved memory below. Be concise and "
    "specific. If the memory does not contain the answer, reply exactly "
    "\"I don't know.\""
)


def build_qa_prompt(context: str, question: str) -> str:
    return "{}\n\nMEMORY:\n{}\n\nQUESTION: {}\nANSWER:".format(
        QA_INSTRUCTIONS, context, question)


JUDGE_INSTRUCTIONS = (
    "You grade whether a predicted answer matches the gold answer in meaning, "
    "ignoring wording and formatting. Return ONLY a JSON object."
)


def build_judge_prompt(question: str, gold: str, predicted: str) -> str:
    return (
        '{}\n\nQuestion: {}\nGold answer: {}\nPredicted answer: {}\n\n'
        'Return: {{"correct": true|false}}'
    ).format(JUDGE_INSTRUCTIONS, question, gold, predicted)
