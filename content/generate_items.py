#!/usr/bin/env python3
"""Generate the knowledge items for the Greek and Italian decks
(deterministic; commit the output).

    content/items-greek.json    el/<letter name>, one per letter
    content/items-italian.json  it/<word>, grammar rules, irregular
                                present paradigms (docs/tutor.md 4.2)

Every card of greek.json, italian.json and
italian-verbs-conjugated.json is linked to the items it tests, so
answering cards feeds the knowledge profile. Keys follow the API's
key grammar; `slug` mirrors Pauk\\Knowledge\\Norm::slug for the
Latin-script labels used here.
"""

from __future__ import annotations

import json
import re
import unicodedata
from pathlib import Path

HERE = Path(__file__).resolve().parent

ARTICLES = ("il ", "lo ", "la ", "i ", "gli ", "le ", "l'", "un ", "uno ", "una ", "un'")
MASCULINE = ("il ", "lo ", "i ", "gli ", "un ", "uno ")
FEMININE = ("la ", "le ", "una ", "un'")

# priority by deck: core vocabulary first (docs/tutor.md 4.3)
PRIORITY = {
    "core-verbs": 90, "core-nouns": 85, "greetings": 90, "courtesy": 90, "survival": 85,
    "zero-to-ten": 85, "eleven-to-twenty": 70, "tens": 60,
    "common-verbs": 65, "common-nouns": 60, "adjectives": 70,
}

IRREGULAR_PRESENT = {"essere", "avere", "fare", "andare", "venire", "dire", "potere", "volere",
                     "dovere", "sapere", "dare", "stare", "uscire"}
REGULAR_RULE = {"parlare": "present-are", "mangiare": "present-are",
                "prendere": "present-ere", "mettere": "present-ere", "vedere": "present-ere",
                "leggere": "present-ere", "scrivere": "present-ere", "vivere": "present-ere",
                "dormire": "present-ire", "finire": "present-isc", "capire": "present-isc"}

RULES = [
    ("present-are", "present tense of -are verbs", "-o, -i, -a, -iamo, -ate, -ano",
     "Regular -are verbs drop -are and add -o, -i, -a, -iamo, -ate, -ano: *parlo, parli, parla, parliamo, parlate, parlano*. "
     "Verbs in -care/-gare add an h before i (*cerchi*), verbs in -iare keep a single i (*mangi*).", 90),
    ("present-ere", "present tense of -ere verbs", "-o, -i, -e, -iamo, -ete, -ono",
     "Regular -ere verbs drop -ere and add -o, -i, -e, -iamo, -ete, -ono: *prendo, prendi, prende, prendiamo, prendete, prendono*.", 85),
    ("present-ire", "present tense of -ire verbs", "-o, -i, -e, -iamo, -ite, -ono",
     "Regular -ire verbs drop -ire and add -o, -i, -e, -iamo, -ite, -ono: *dormo, dormi, dorme, dormiamo, dormite, dormono*.", 80),
    ("present-isc", "present tense of -ire verbs with -isc-", "-isco, -isci, -isce, -iamo, -ite, -iscono",
     "Many -ire verbs insert -isc- in all persons except noi and voi: *finisco, finisci, finisce, finiamo, finite, finiscono*.", 70),
    ("noun-gender", "gender of nouns", "-o mostly masculine, -a mostly feminine, -e either",
     "Nouns in -o are usually masculine, in -a usually feminine (exceptions: *il problema*, *la mano*); nouns in -e can be either and must be learnt.", 85),
    ("noun-plural", "plural of nouns", "-o → -i, -a → -e, -e → -i",
     "Masculine -o becomes -i (*ragazzo → ragazzi*), feminine -a becomes -e (*casa → case*), -e becomes -i; -co/-go and -ca/-ga often add h (*amica → amiche*, but *amico → amici*).", 80),
    ("definite-article", "definite article", "il, lo, l', la, i, gli, le",
     "Masculine: *il* (before most consonants), *lo* (before s+consonant, z, gn, ps), *l'* (before a vowel); plural *i* / *gli*. "
     "Feminine: *la*, *l'* before a vowel; plural *le*.", 85),
    ("indefinite-article", "indefinite article", "un, uno, una, un'",
     "Masculine *un*, or *uno* before s+consonant, z, gn, ps; feminine *una*, or *un'* before a vowel.", 80),
    ("preposition-a-in", "a vs in for places", "a + city, in + country/region",
     "Use *a* with cities (*Abito a Roma*, *Vado a Milano*) and *in* with countries and regions (*Vado in Italia*).", 70),
]


def slug(text: str) -> str:
    text = unicodedata.normalize("NFKD", text.lower())
    text = "".join(ch for ch in text if not unicodedata.combining(ch))
    return re.sub(r"[^a-z0-9]+", "-", text).strip("-")


def strip_article(word: str) -> tuple[str, str | None]:
    lower = word.lower()
    for article in ARTICLES:
        if lower.startswith(article):
            gender = "m" if article in MASCULINE else "f" if article in FEMININE else None
            return word[len(article):], gender
    return word, None


def bold(text: str) -> str:
    return re.search(r"\*\*(.*?)\*\*", text).group(1)


def greek() -> dict:
    deck = json.loads((HERE / "greek.json").read_text(encoding="utf-8"))
    from generate_greek import LETTERS  # (lower, upper, name, variants)

    items = []
    by_symbol = {}
    for position, (lower, upper, name, variants) in enumerate(LETTERS, start=1):
        items.append({
            "key": name, "kind": "symbol", "label_md": lower, "gloss_md": name,
            "body_md": f"Letter {position} of 24. Uppercase **{upper}**, lowercase **{lower}**."
                       + (f" Also spelled {', '.join(variants)}." if variants else ""),
            "attrs": {"uppercase": upper, "position": position, "source": "greek.json"},
            "priority": 80, "level": 1, "dirs": ["greek"],
        })
        for symbol in [upper, *[s.strip() for s in lower.split("/")]]:
            by_symbol[symbol] = name
    card_links = []
    for card in deck["cards"]:
        symbol = bold(card["question_md"])
        name = by_symbol.get(symbol) or by_symbol[symbol.split("/")[0].strip()]
        card_links.append({"card": card["question_md"], "item": name})
    return {"space": "el", "dirs": ["greek"], "items": items, "card_links": card_links}


def italian() -> dict:
    deck = json.loads((HERE / "italian.json").read_text(encoding="utf-8"))
    conj = json.loads((HERE / "italian-verbs-conjugated.json").read_text(encoding="utf-8"))
    items: dict[str, dict] = {}
    card_links: list[dict] = []

    def add(key: str, item: dict) -> None:
        if key not in items:
            items[key] = {"key": key, **item}

    for key, label, gloss, body, priority in RULES:
        add(key, {"kind": "rule", "label_md": label, "gloss_md": gloss, "body_md": body,
                  "attrs": {"source": "italian.json"}, "priority": priority, "level": 1,
                  "dirs": ["italian/grammar"]})
    items["definite-article"]["links"] = [{"rel": "requires", "to": "noun-gender"}]
    items["indefinite-article"]["links"] = [{"rel": "requires", "to": "noun-gender"}]

    # vocabulary from the translate cards
    for card in deck["cards"]:
        if card["type"] != "text":
            continue
        english = bold(card["question_md"])
        deck_dir = card["dirs"][0]
        section = deck_dir.split("/")[2] if deck_dir.count("/") >= 2 else deck_dir.split("/")[-1]
        group = deck_dir.split("/")[1]
        # nouns are keyed without their article; the article gives the gender
        strip = strip_article if group == "nouns" else (lambda w: (w, None))
        first, gender = strip(card["accepted_answers"][0])
        # alternatives without punctuation-only variants and without the headword itself
        seen = {first.strip(" ?!.").lower()}
        alternatives = []
        for answer in card["accepted_answers"][1:]:
            alt = strip(answer)[0].strip(" ?!.")
            if alt.lower() not in seen:
                seen.add(alt.lower())
                alternatives.append(alt)
        kind = "phrase" if group == "phrases" or " " in first else "word"
        attrs = {"source": "italian.json"}
        if group in ("verbs", "nouns", "adjectives", "numbers"):
            attrs["pos"] = {"verbs": "verb", "nouns": "noun", "adjectives": "adj", "numbers": "num"}[group]
        if gender:
            attrs["gender"] = gender
        key = slug(first)
        add(key, {"kind": kind, "label_md": first, "gloss_md": english,
                  "body_md": f"Also: {', '.join(sorted(alternatives))}." if alternatives else "",
                  "attrs": attrs, "priority": PRIORITY.get(section, PRIORITY.get(deck_dir.split('/')[-1], 60)),
                  "level": 1, "dirs": [deck_dir]})
        card_links.append({"card": card["question_md"], "item": key})

    def verb_refs(verb: str) -> list[str]:
        if verb in IRREGULAR_PRESENT:
            return [f"{verb}.pres"]
        return [REGULAR_RULE[verb], verb]

    # irregular present paradigms and missing verb lexemes
    verbs = sorted(IRREGULAR_PRESENT | set(REGULAR_RULE))
    for verb in verbs:
        gloss = next((c["question_md"] for c in conj["cards"] if f"**{verb}**" in c["question_md"] or f"*{verb}*" in c["question_md"]), "")
        meaning = re.search(r"\(\*?" + verb + r"\*?,? ?([^)]*)\)", gloss) or re.search(r"\*\*" + verb + r"\*\* \(([^)]*)\)", gloss)
        add(verb, {"kind": "word", "label_md": verb, "gloss_md": meaning.group(1).strip() if meaning else "",
                   "body_md": "", "attrs": {"pos": "verb", "source": "italian-verbs-conjugated.json"},
                   "priority": 80, "level": 1, "dirs": ["italian/verbs"]})
    for verb in sorted(IRREGULAR_PRESENT):
        add(f"{verb}.pres", {"kind": "form", "label_md": f"{verb} — present tense", "gloss_md": "", "body_md": "",
                             "attrs": {"tense": "present", "source": "italian-verbs-conjugated.json"},
                             "priority": 85, "level": 1,
                             "dirs": [f"italian/verbs/conjugation/present/{verb}"],
                             "links": [{"rel": "requires", "to": verb}]})

    # conjugation deck: the forms (irregular) or rule + lexeme (regular)
    for card in conj["cards"]:
        last = card["dirs"][0].split("/")[-1]
        if last == "essere-avere":   # contrast cards test both paradigms
            card_links += [{"card": card["question_md"], "item": ref} for ref in ("essere.pres", "avere.pres")]
            continue
        verb = last if last in items else re.search(r"\*\*?(\w+)\*\*?", card["question_md"]).group(1)
        for ref in verb_refs(verb):
            card_links.append({"card": card["question_md"], "item": ref})
        if verb in IRREGULAR_PRESENT and card["type"] == "match":
            pairs = "; ".join(f"{p['left_md']} {p['right_md']}" for p in card["pairs"])
            items[f"{verb}.pres"]["gloss_md"] = pairs
    # irregular paradigms without a match card: take the text cards
    for verb in IRREGULAR_PRESENT:
        form = items[f"{verb}.pres"]
        if not form["gloss_md"]:
            cells = [(re.search(r"for \*\*(.*?)\*\*", c["question_md"]), c["accepted_answers"][0])
                     for c in conj["cards"] if c["type"] == "text" and f"**{verb}**" in c["question_md"]]
            form["gloss_md"] = "; ".join(f"{m.group(1)} {a}" for m, a in cells if m)

    # grammar mc cards in the main deck
    for card in deck["cards"]:
        if card["type"] != "mc":
            continue
        q = card["question_md"]
        if q.startswith("Which definite article"):
            refs = ["definite-article"]
        elif q.startswith("Which indefinite article"):
            refs = ["indefinite-article"]
        elif q.startswith("Which of these Italian nouns"):
            refs = ["noun-gender"]
        elif q.startswith("What is the plural"):
            refs = ["noun-plural"]
        elif q.startswith("Which preposition"):
            refs = ["preposition-a-in"]
        elif q.startswith("Complete the sentence"):
            refs = verb_refs(re.search(r"— \*(\w+)\*", q).group(1))
        else:
            raise ValueError(f"unmapped grammar card: {q}")
        card_links += [{"card": q, "item": ref} for ref in refs]

    for verb in IRREGULAR_PRESENT:
        if not items[f"{verb}.pres"]["gloss_md"]:
            raise ValueError(f"no paradigm found for {verb}")
    dirs = sorted({d for item in items.values() for d in item["dirs"]})
    return {"space": "it", "dirs": dirs, "items": list(items.values()), "card_links": card_links}


def main() -> None:
    import sys

    sys.path.insert(0, str(HERE))
    for name, data in (("items-greek.json", greek()), ("items-italian.json", italian())):
        (HERE / name).write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        print(f"{name}: {len(data['items'])} items, {len(data['card_links'])} card links")


if __name__ == "__main__":
    main()
