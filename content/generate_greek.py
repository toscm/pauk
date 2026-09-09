#!/usr/bin/env python3
"""Generate content/greek.json (deterministic; commit the output).

Three quiz styles per letter: name the lowercase symbol (free
text), name the uppercase symbol (free text), and multiple
choice with confusable distractors.
"""

import json
import random
from pathlib import Path

# (lowercase, uppercase, primary name, accepted variants)
LETTERS = [
    ("α", "Α", "alpha", []),
    ("β", "Β", "beta", []),
    ("γ", "Γ", "gamma", []),
    ("δ", "Δ", "delta", []),
    ("ε", "Ε", "epsilon", []),
    ("ζ", "Ζ", "zeta", []),
    ("η", "Η", "eta", []),
    ("θ", "Θ", "theta", []),
    ("ι", "Ι", "iota", ["jota"]),
    ("κ", "Κ", "kappa", []),
    ("λ", "Λ", "lambda", ["lamda"]),
    ("μ", "Μ", "mu", ["my"]),
    ("ν", "Ν", "nu", ["ny"]),
    ("ξ", "Ξ", "xi", []),
    ("ο", "Ο", "omicron", ["omikron"]),
    ("π", "Π", "pi", []),
    ("ρ", "Ρ", "rho", []),
    ("σ / ς", "Σ", "sigma", []),
    ("τ", "Τ", "tau", []),
    ("υ", "Υ", "upsilon", ["ypsilon"]),
    ("φ", "Φ", "phi", []),
    ("χ", "Χ", "chi", []),
    ("ψ", "Ψ", "psi", []),
    ("ω", "Ω", "omega", []),
]

# Letters that are genuinely mixed up; used to pick distractors.
CONFUSABLE = {
    "nu": ["upsilon", "eta", "mu"],
    "upsilon": ["nu", "gamma", "chi"],
    "zeta": ["xi", "sigma", "psi"],
    "xi": ["zeta", "chi", "psi"],
    "eta": ["nu", "mu", "iota"],
    "phi": ["psi", "theta", "chi"],
    "psi": ["phi", "xi", "chi"],
    "omicron": ["omega", "theta", "sigma"],
    "omega": ["omicron", "sigma", "upsilon"],
    "epsilon": ["eta", "xi", "sigma"],
    "rho": ["pi", "phi", "beta"],
}


def main() -> None:
    rng = random.Random(2026)
    names = [name for _, _, name, _ in LETTERS]
    dirs = [
        "greek",
        "greek/lowercase",
        "greek/uppercase",
        "greek/multiple-choice",
    ]
    cards = []
    for lower, upper, name, variants in LETTERS:
        cards.append({
            "dirs": ["greek/lowercase"],
            "type": "text",
            "question_md": f"Name this Greek letter: **{lower}**",
            "accepted_answers": [name, *variants],
        })
        cards.append({
            "dirs": ["greek/uppercase"],
            "type": "text",
            "question_md": f"Name this Greek letter (uppercase): **{upper}**",
            "accepted_answers": [name, *variants],
        })
        pool = CONFUSABLE.get(name) or rng.sample([n for n in names if n != name], 3)
        distractors = list(pool[:3])
        while len(distractors) < 3:
            extra = rng.choice([n for n in names if n != name and n not in distractors])
            distractors.append(extra)
        options = [{"text_md": name, "correct": True}] + [
            {"text_md": d, "correct": False} for d in distractors
        ]
        rng.shuffle(options)
        cards.append({
            "dirs": ["greek/multiple-choice"],
            "type": "mc",
            "question_md": f"Which Greek letter is this: **{lower}**?",
            "options": options,
        })

    out = Path(__file__).parent / "greek.json"
    out.write_text(
        json.dumps({"dirs": dirs, "dir_links": [], "cards": cards},
                   ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    print(f"wrote {out} ({len(cards)} cards)")


if __name__ == "__main__":
    main()
