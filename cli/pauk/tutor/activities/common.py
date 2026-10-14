"""Helpers shared by the activity types: item refs, name grading."""

from __future__ import annotations

import json
import re
import unicodedata
from functools import lru_cache
from importlib import resources

# space/key with the key grammar of docs/tutor.md 4.1
REF = re.compile(r"^[a-z]+/[a-z0-9]+(?:-[a-z0-9]+)*(?:\.[a-z0-9]+(?:-[a-z0-9]+)*)*$")
OUTCOMES = ("fail", "hard", "good", "easy")
GRADE_OUTCOME = {"exact": "good", "typo": "hard", "wrong": "fail"}
TEACHER = "teacher"
LEARNER = "learner"

# leading articles ignored when naming things ("il pane" = "pane")
ARTICLES = {
    "it": ("il ", "lo ", "la ", "l ", "i ", "gli ", "le ", "un ", "uno ", "una "),
    "de": ("der ", "die ", "das ", "ein ", "eine "),
    "en": ("the ", "a ", "an "),
}
UMLAUTS = str.maketrans({"ä": "ae", "ö": "oe", "ü": "ue", "ß": "ss"})


def check_ref(ref, where: str) -> str:
    if not isinstance(ref, str) or not REF.match(ref):
        raise ValueError(f"{where}: '{ref}' is not an item ref like it/pane or concepts/leipzig")
    return ref


def normalize(text: str, umlauts: bool = False) -> str:
    """Like the API's Text::normalize (lowercase, fold diacritics, drop
    punctuation); `umlauts` spells ä/ö/ü/ß as ae/oe/ue/ss first."""
    text = str(text).lower().strip()
    if umlauts:
        text = text.translate(UMLAUTS)
    text = unicodedata.normalize("NFKD", text.replace("ß", "ss"))
    text = "".join(c for c in text if not unicodedata.combining(c))
    return " ".join(re.sub(r"[^\w\s]+|_", " ", text).split())


def _strip_article(text: str, language: str | None) -> str:
    for article in ARTICLES.get(language or "", ()):
        if text.startswith(article) and len(text) > len(article):
            return text[len(article):]
    return text


def _levenshtein(a: str, b: str) -> int:
    prev = list(range(len(b) + 1))
    for i, ca in enumerate(a, 1):
        cur = [i]
        for j, cb in enumerate(b, 1):
            cur.append(min(prev[j] + 1, cur[j - 1] + 1, prev[j - 1] + (ca != cb)))
        prev = cur
    return prev[-1]


def grade_name(answer: str, accepted: list[str], language: str | None = None) -> str:
    """"exact", "typo" or "wrong", as the API grades text answers:
    normalized comparison, then one edit per 8 characters for names of
    4+ characters. Both spellings of umlauts count ("Nürnberg",
    "Nuernberg", "Nurnberg"), and a leading article is optional."""
    def forms(text: str) -> set[str]:
        return {_strip_article(normalize(text, u), language) for u in (False, True)}

    given = forms(answer or "")
    if not any(given):
        return "wrong"
    candidates = [form for name in accepted for form in forms(name)]
    if given & set(candidates):
        return "exact"
    for norm in candidates:
        if len(norm) >= 4 and any(_levenshtein(g, norm) <= max(1, len(norm) // 8) for g in given):
            return "typo"
    return "wrong"


def overall(outcomes: list[str]) -> str:
    """One outcome for a whole activity from its per-item outcomes."""
    if not outcomes:
        return "none"
    share = sum(o != "fail" for o in outcomes) / len(outcomes)
    return "good" if share >= 0.9 else "hard" if share >= 0.6 else "fail"


@lru_cache(maxsize=4)
def load_map(name: str) -> dict:
    if not re.match(r"^[a-z0-9-]+$", str(name)):
        raise ValueError(f"bad map name '{name}'")
    path = resources.files("pauk.data").joinpath("activities", "maps", f"{name}.json")
    if not path.is_file():
        raise ValueError(f"unknown map '{name}' (known: germany)")
    return json.loads(path.read_text(encoding="utf-8"))
