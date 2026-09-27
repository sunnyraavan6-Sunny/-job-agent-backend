"""
Classifies an inbound reply's text into the categories the dashboard tracks
(spec section 4): positive, negative, neutral, interview opportunity,
rejection, follow-up required, action required.

Keyword-based rather than ML-based, deliberately: it's transparent, needs no
model download, and is easy to extend as you see real reply patterns. Order
matters -- more specific/high-signal categories are checked first so a reply
that mentions both "unfortunately" and a question still gets classified as
a rejection, not a generic follow-up.
"""
import re

_REJECTION_PATTERNS = [
    r"\bunfortunately\b", r"\bnot moving forward\b", r"\bother candidates\b",
    r"\bdecided to (go|move) (with|forward)\b", r"\bnot (a|the right) (fit|match)\b",
    r"\bposition (has been|is) filled\b", r"\bwon'?t be (moving|proceeding)\b",
]
_INTERVIEW_PATTERNS = [
    r"\bschedule (a|an) (call|interview|chat)\b", r"\bavailable for a call\b",
    r"\bnext steps?\b", r"\bwould like to (speak|chat|meet)\b", r"\bbook (some|a) time\b",
    r"\bphone screen\b", r"\bset up (a|an) (interview|call)\b",
]
_NEGATIVE_PATTERNS = [
    r"\bnot interested\b", r"\bno thank you\b", r"\bplease remove\b", r"\bunsubscribe\b",
    r"\bstop (contacting|emailing)\b",
]
_POSITIVE_PATTERNS = [
    r"\binterested\b", r"\blet'?s connect\b", r"\bsounds good\b", r"\bhappy to (chat|discuss|connect)\b",
    r"\blooking forward\b",
]


def _matches_any(text: str, patterns: list[str]) -> bool:
    return any(re.search(p, text, re.IGNORECASE) for p in patterns)


def classify_reply(text: str) -> dict:
    """
    Returns {"category": ..., "outreach_status": ...} where category is the
    granular dashboard label and outreach_status maps onto the OutreachStatus
    enum (replied_positive / replied_negative / replied_neutral).
    """
    if not text or not text.strip():
        return {"category": "neutral", "outreach_status": "replied_neutral"}

    if _matches_any(text, _REJECTION_PATTERNS):
        return {"category": "rejection", "outreach_status": "replied_negative"}

    if _matches_any(text, _INTERVIEW_PATTERNS):
        return {"category": "interview_opportunity", "outreach_status": "replied_positive"}

    if _matches_any(text, _NEGATIVE_PATTERNS):
        return {"category": "negative", "outreach_status": "replied_negative"}

    if _matches_any(text, _POSITIVE_PATTERNS):
        return {"category": "positive", "outreach_status": "replied_positive"}

    if "?" in text:
        return {"category": "action_required", "outreach_status": "replied_neutral"}

    return {"category": "neutral", "outreach_status": "replied_neutral"}
