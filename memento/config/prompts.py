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
    "Answer using ONLY the information below: a KNOWN USER PREFERENCES block (a "
    "durable profile of the user's tastes, constraints, and habits) and MEMORIES "
    "(a JSON array of timestamped items sorted oldest to newest; each has date, "
    "days_ago, and text).\n"
    "Think briefly on a scratchpad, then give the final line as 'ANSWER: <answer>'.\n"
    "Scratchpad rules:\n"
    "1. Note the items relevant to the question, with their dates.\n"
    "2. If items conflict, use the one with the MOST RECENT date.\n"
    "3. If the question is about timing/duration, compute it from the dates or "
    "days_ago and show the arithmetic.\n"
    "4. If the question is about the user's tastes/choices, APPLY the KNOWN USER "
    "PREFERENCES.\n"
    "If the answer is not present, the final line must be exactly "
    "'ANSWER: I don't know.'"
)


def build_qa_prompt(context: str, question: str) -> str:
    return "{}\n\n{}\n\nQUESTION: {}\n".format(QA_INSTRUCTIONS, context, question)


# ---- preference / profile extraction (the durable, always-injected profile) ----

PREFERENCE_EXTRACTION_INSTRUCTIONS = (
    "From the conversation below, list the USER's preferences: tastes, likes, "
    "dislikes, constraints, habits, values, and standing instructions. Include "
    "ones that are IMPLIED but not stated outright (e.g. 'I get anxious in crowds' "
    "implies a preference for quiet places). Resolve references so each statement "
    "stands alone.\n"
    "Return ONLY a JSON array; [] if none. Each item: "
    '{"category":"2-4 word topic","statement":"a standalone preference",'
    '"polarity":"like|dislike|constraint|habit|value"}'
)


def build_preference_prompt(conversation: str) -> str:
    return "{}\n\nCONVERSATION:\n{}\n".format(PREFERENCE_EXTRACTION_INSTRUCTIONS, conversation)


JUDGE_INSTRUCTIONS = (
    "You grade whether a predicted answer matches the gold answer in meaning, "
    "ignoring wording and formatting. Return ONLY a JSON object."
)


def build_judge_prompt(question: str, gold: str, predicted: str) -> str:
    return (
        '{}\n\nQuestion: {}\nGold answer: {}\nPredicted answer: {}\n\n'
        'Return: {{"correct": true|false}}'
    ).format(JUDGE_INSTRUCTIONS, question, gold, predicted)


# ---- fact extraction (turn raw activity into atomic, indexable facts) ----

FACT_EXTRACTION_INSTRUCTIONS = (
    "Extract atomic, self-contained statements about the USER from the "
    "conversation below. Each must stand alone without the surrounding context "
    "(resolve pronouns and references). Capture decisions, states, attributes, "
    "plans, and events as kind='fact' or 'event'. Capture the user's tastes, "
    "likes, dislikes, constraints, habits, values, and standing instructions "
    "(INCLUDING ones implied but not stated outright) as kind='preference'. "
    "Ignore small talk and assistant chatter.\n\n"
    "Return ONLY a JSON array; [] if nothing. Each item:\n"
    '{"kind":"fact|preference|event","content":"a single standalone statement",'
    '"subject":"2-4 word topic key","updates":true|false}\n'
    "Set updates=true when it changes or replaces an earlier state "
    "(e.g. a move, a switch, a new value)."
)


def build_extraction_prompt(conversation: str) -> str:
    return "{}\n\nCONVERSATION:\n{}\n".format(FACT_EXTRACTION_INSTRUCTIONS, conversation)


# ---- time-aware query expansion ----

TIME_EXPANSION_INSTRUCTIONS = (
    "Given the user's question and the current date, determine the time window "
    "the answer should come from. Return ONLY JSON: "
    '{"from":"YYYY-MM-DD"|null,"to":"YYYY-MM-DD"|null}. '
    "Use null for an open bound. Return both null if the question is not time-scoped."
)


def build_time_expansion_prompt(question: str, as_of: str) -> str:
    return "{}\n\nCurrent date: {}\nQuestion: {}\n".format(
        TIME_EXPANSION_INSTRUCTIONS, as_of, question)


# ---- multi-hop query decomposition ----

DECOMPOSITION_INSTRUCTIONS = (
    "Break the question into the minimal set of standalone sub-questions whose "
    "answers together answer it. If it is already simple, return it unchanged as "
    "the single item. Return ONLY JSON: {\"subquestions\":[\"...\"]} (max 4)."
)


def build_decomposition_prompt(question: str) -> str:
    return "{}\n\nQuestion: {}\n".format(DECOMPOSITION_INSTRUCTIONS, question)


# ---- relevance reranking ----

RERANK_INSTRUCTIONS = (
    "Rank the candidate memories by how useful each is for answering the "
    "question. Return ONLY JSON: {\"order\":[indexes most useful first]} using "
    "the given indexes; include only genuinely relevant ones."
)


def build_rerank_prompt(question: str, candidates: str) -> str:
    return "{}\n\nQuestion: {}\n\nCANDIDATES:\n{}\n".format(
        RERANK_INSTRUCTIONS, question, candidates)
