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


# memory aids merged into attrs: mnemonic (an Eselsbrücke, "(de)" if
# German) and anecdote (a short true fact, often the etymology)
MEMORY: dict[str, dict[str, str]] = {
    # Greek letters
    "el/alpha": {"anecdote": "*Alpha* + *beta* gave us the word *alphabet*."},
    "el/beta": {"anecdote": "In modern Greek it is called *vita* and sounds like v."},
    "el/gamma": {"anecdote": "In modern Greek it sounds like a y before e and i sounds."},
    "el/delta": {"anecdote": "River deltas are named after the triangular capital Δ; Herodotus first used it for the Nile delta."},
    "el/epsilon": {"anecdote": "*E psilon* means 'plain e', to tell it apart from the diphthong αι with the same sound."},
    "el/eta": {"anecdote": "The capital Η became the Latin letter H; in modern Greek η sounds like i."},
    "el/theta": {"mnemonic": "θ sounds like *th* in English *think*."},
    "el/iota": {"anecdote": "'Not one iota' means not the slightest bit, because ι is the smallest letter."},
    "el/mu": {"mnemonic": "μ is the micro sign: μm = micrometre."},
    "el/nu": {"mnemonic": "ν looks like a v but is an n!"},
    "el/omicron": {"anecdote": "*O mikron* means 'small o' (as in *micro*), the counterpart of *omega*."},
    "el/pi": {"mnemonic": "π = 3.14159…, the ratio of a circle's circumference to its diameter."},
    "el/rho": {"mnemonic": "ρ looks like a p but is an r!"},
    "el/sigma": {"mnemonic": "ς is used only at the end of a word; the capital Σ is the sum sign."},
    "el/upsilon": {"anecdote": "*U psilon* means 'plain u', to tell it apart from the diphthong οι."},
    "el/phi": {"anecdote": "The golden ratio (1.618…) is usually written φ."},
    "el/chi": {"mnemonic": "(de) χ sieht aus wie x, klingt aber wie das ch in *Bach*."},
    "el/psi": {"anecdote": "ψ is the symbol of psychology (from *psyche*, soul)."},
    "el/omega": {"anecdote": "*O mega* means 'big o'; 'the Alpha and the Omega' means the beginning and the end."},
    # Italian grammar
    "it/present-isc": {"mnemonic": "In the conjugation table the -isc- forms (io, tu, lui/lei, loro) draw the shape of a boot, like Italy."},
    "it/present-are": {"mnemonic": "*noi* always ends in -iamo, in every conjugation: *parliamo, prendiamo, dormiamo*."},
    "it/noun-gender": {"anecdote": "Nouns in -ma from Greek are masculine: *il problema, il tema, il sistema*."},
    "it/definite-article": {"mnemonic": "*lo* for the hissing and buzzing starts: *lo studente, lo zio*."},
    "it/indefinite-article": {"mnemonic": "The apostrophe marks a missing a, so only the feminine has one: *un'amica*, but *un amico*."},
    "it/preposition-a-in": {"mnemonic": "Short word, small place (*a Roma*); longer word, larger place (*in Italia*)."},
    # Italian verbs
    "it/essere": {"mnemonic": "(de) *essere* – die Essenz: das, was du bist."},
    "it/avere": {"mnemonic": "(de) *avere* ≈ haben: beide stammen von lateinisch *habere*."},
    "it/fare": {"anecdote": "From Latin *facere*, which is why some forms are long: *facciamo, facevo*."},
    "it/andare": {"anecdote": "*vado, vai, va, vanno* come from Latin *vadere*; *andiamo, andate* come from a different root."},
    "it/venire": {"mnemonic": "(de) *venire* steckt im *Advent*, der 'Ankunft'."},
    "it/dire": {"anecdote": "From Latin *dicere*, hence *dico, diciamo* and English *dictate*."},
    "it/potere": {"mnemonic": "English *potent* and *potential*: what you are able to do."},
    "it/volere": {"mnemonic": "English *voluntary*: what you want to do."},
    "it/dovere": {"anecdote": "As a noun, *il dovere* means 'the duty'."},
    "it/sapere": {"anecdote": "Latin *sapere* meant 'to taste, to be wise', hence *Homo sapiens*; *sapere di* still means 'to taste of'."},
    "it/vedere": {"mnemonic": "(de) *Video* ist lateinisch und heißt 'ich sehe'."},
    "it/dare": {"mnemonic": "(de) Ein *Datum* ist lateinisch 'das Gegebene'."},
    "it/stare": {"mnemonic": "Like English *stay* and *state*: *come stai?* = how do you stand?"},
    "it/parlare": {"mnemonic": "(de) Im *Parlament* wird geredet."},
    "it/mangiare": {"anecdote": "Borrowed from Old French *mangier*, from Latin *manducare* 'to chew'."},
    "it/bere": {"anecdote": "From Latin *bibere*, which is why the stem is *bev-*: *bevo, bevuto*; cf. English *beverage*."},
    "it/prendere": {"anecdote": "From Latin *prehendere* 'to grasp', as in English *apprehend*."},
    "it/mettere": {"anecdote": "From Latin *mittere*, the root of English *emit, submit, transmit*."},
    "it/uscire": {"mnemonic": "*uscita* is the EXIT sign you see everywhere."},
    "it/dormire": {"mnemonic": "(de) Im *Dormitorium* (Schlafsaal) wird geschlafen."},
    "it/lavorare": {"anecdote": "From Latin *laborare*, like English *labour*."},
    "it/abitare": {"mnemonic": "English *inhabit* and *habitat*."},
    "it/amare": {"mnemonic": "(de) *Amor* schießt mit Pfeilen: *amare* = lieben."},
    "it/aiutare": {"mnemonic": "*Aiuto!* is the cry for 'Help!'."},
    "it/aprire": {"mnemonic": "English *aperture*: an opening."},
    "it/chiudere": {"anecdote": "From Latin *claudere*; Italian *chi-* often replaces Latin *cl-*: *chiave* (clavis), *chiamare* (clamare)."},
    "it/partire": {"mnemonic": "*Partenze* is the departures board at the station."},
    "it/ascoltare": {"anecdote": "From Latin *auscultare*; doctors still *auscultate* with a stethoscope."},
    "it/aspettare": {"anecdote": "From Latin *exspectare*, like English *expect*."},
    "it/ballare": {"mnemonic": "(de) Auf dem *Ball* wird getanzt."},
    "it/cantare": {"mnemonic": "(de) *Kantate* und *Kantor* haben mit Singen zu tun."},
    "it/capire": {"mnemonic": "(de) *capire* = kapieren; das deutsche Wort kommt von lateinisch *capere*."},
    "it/cercare": {"anecdote": "From Latin *circare* 'to go around'; English *search* comes from the same word."},
    "it/chiamare": {"anecdote": "From Latin *clamare* 'to shout', as in English *exclaim*."},
    "it/conoscere": {"mnemonic": "English *connoisseur*: someone who knows."},
    "it/correre": {"mnemonic": "(de) Der *Kurier* rennt."},
    "it/cucinare": {"mnemonic": "(de) In der *cucina* (Küche) wird gekocht."},
    "it/giocare": {"anecdote": "From Latin *iocus* 'joke, game', like English *joke*."},
    "it/guardare": {"mnemonic": "False friend: not 'to guard' but 'to look', though a guard is someone who watches."},
    "it/leggere": {"mnemonic": "(de) Eine *Legende* ist lateinisch 'das zu Lesende'."},
    "it/pagare": {"anecdote": "From Latin *pacare* 'to pacify': paying pacified the creditor."},
    "it/pensare": {"mnemonic": "English *pensive*: lost in thought."},
    "it/scrivere": {"mnemonic": "(de) *scrivere* = schreiben, beide von lateinisch *scribere*."},
    "it/sentire": {"mnemonic": "Means both 'to hear' and 'to feel', like English *sense* and *sentiment*."},
    "it/trovare": {"anecdote": "Related to the troubadours (*trovatori*), the 'finders' of verses."},
    "it/viaggiare": {"anecdote": "From Latin *viaticum*, provisions for the road; English *voyage* has the same origin."},
    "it/finire": {"mnemonic": "(de) Im *Finale* ist alles zu Ende."},
    "it/vivere": {"mnemonic": "English *vivid* and *survive*."},
    # Italian nouns
    "it/casa": {"anecdote": "Latin *casa* meant 'hut'; the Latin word for house, *domus*, survives in *duomo*."},
    "it/uomo": {"mnemonic": "(de) *uomo* kommt von *homo*, wie in *Homo sapiens*; Plural: *gli uomini*."},
    "it/donna": {"anecdote": "From Latin *domina* 'lady of the house'; *Madonna* means 'my lady'."},
    "it/bambino": {"anecdote": "Bambi got his name from Italian *bambino*."},
    "it/acqua": {"mnemonic": "(de) Im *Aquarium* ist Wasser."},
    "it/pane": {"anecdote": "Your *companions* are literally the people you share bread with (Latin *com* + *panis*)."},
    "it/libro": {"mnemonic": "False friend: *libreria* is a bookshop; a library is a *biblioteca*."},
    "it/giorno": {"anecdote": "From Latin *diurnus* 'daily'; *giornale* (newspaper) is English *journal*."},
    "it/notte": {"mnemonic": "(de) Aus -cht wird -tt: Nacht → *notte*, acht → *otto*."},
    "it/anno": {"mnemonic": "The double n matters: *anno* is 'year', *ano* is 'anus'. *Buon anno!*"},
    "it/citta": {"anecdote": "From Latin *civitas*, like English *city* and *civic*."},
    "it/strada": {"mnemonic": "(de) *strada* = Straße, beide von lateinisch *via strata* 'gepflasterter Weg'."},
    "it/scuola": {"anecdote": "Like German *Schule*, from Greek *scholē*, which originally meant 'leisure'."},
    "it/amico": {"mnemonic": "A friend is someone you love: *amico* comes from *amare*."},
    "it/fratello": {"anecdote": "A diminutive of Latin *frater*, as in *fraternity*."},
    "it/sorella": {"anecdote": "A diminutive of Latin *soror*, as in *sorority*."},
    "it/cane": {"anecdote": "The Canary Islands are named after dogs (Latin *canes*), not birds."},
    "it/gatto": {"mnemonic": "(de) *gatto*, Katze, cat: alle von spätlateinisch *cattus*."},
    "it/latte": {"mnemonic": "Order a *latte* in Italy and you get a glass of milk; ask for a *caffellatte*."},
    "it/caffe": {"anecdote": "In Italy *un caffè* is an espresso."},
    "it/porta": {"mnemonic": "English *portal* and *porter* (door-keeper)."},
    "it/nome": {"mnemonic": "(de) *Nomen est omen*: der Name ist ein Zeichen."},
    "it/finestra": {"mnemonic": "(de) *finestra* = Fenster, beide von lateinisch *fenestra*."},
    "it/tavolo": {"mnemonic": "(de) *tavolo* = Tafel, beide von lateinisch *tabula*."},
    "it/sedia": {"mnemonic": "From *sedere* 'to sit', like English *sedentary*."},
    "it/cucina": {"mnemonic": "(de) *cucina* = Küche, beide von lateinisch *coquina*."},
    "it/bagno": {"anecdote": "From Latin *balneum* 'bath'; *bagno* is both the bathroom and the bath."},
    "it/camera": {"anecdote": "False friend: *camera* is a room; the photo camera is named after the *camera obscura*, 'dark room'."},
    "it/chiave": {"anecdote": "From Latin *clavis*, like *clef* and *clavicle*; *chi-* often replaces Latin *cl-*."},
    "it/denaro": {"anecdote": "Named after the Roman silver coin *denarius*, like Spanish *dinero*."},
    "it/negozio": {"anecdote": "From Latin *negotium* 'business', as in *negotiate*."},
    "it/mercato": {"mnemonic": "(de) *mercato* = Markt, beide von lateinisch *mercatus*."},
    "it/albergo": {"anecdote": "A Germanic loanword related to German *Herberge*."},
    "it/mare": {"mnemonic": "(de) Die *Marine* fährt aufs Meer."},
    "it/sole": {"mnemonic": "(de) *Solar*energie kommt von der Sonne."},
    "it/luna": {"anecdote": "*lunedì*, Monday, is the day of the moon."},
    "it/fiore": {"mnemonic": "(de) Der *Florist* verkauft Blumen."},
    "it/albero": {"anecdote": "*albero* is also the mast of a ship."},
    "it/frutta": {"anecdote": "*frutta* is fruit in general; a single piece of fruit is *un frutto*."},
    "it/carne": {"anecdote": "*Carnevale* is traditionally explained as *carne levare*, 'remove meat', before Lent."},
    "it/pesce": {"mnemonic": "(de) Das Sternzeichen Fische heißt *Pisces*."},
    "it/formaggio": {"anecdote": "From *forma*, the mould the cheese was pressed in; French *fromage* is the same word."},
    "it/uovo": {"mnemonic": "The plural is feminine: *le uova*. (de) *oval* = eiförmig."},
    "it/pomodoro": {"anecdote": "*Pomo d'oro*, 'golden apple': the first tomatoes in Italy were probably yellow."},
    "it/zucchero": {"anecdote": "From Arabic *sukkar*, like English *sugar*."},
    # Italian adjectives
    "it/bello": {"mnemonic": "(de) Ein *Belvedere* ist ein Ort mit schöner Aussicht."},
    "it/buono": {"anecdote": "French *bonbon*, 'good-good', comes from the same Latin *bonus*."},
    "it/piccolo": {"mnemonic": "The *piccolo* is the small flute."},
    "it/nuovo": {"mnemonic": "English *novel* and *innovate*: something new."},
    "it/giovane": {"mnemonic": "English *juvenile*, from Latin *iuvenis*."},
    "it/alto": {"anecdote": "In music, *alto* was originally the part sung above the tenor."},
    "it/basso": {"mnemonic": "(de) Der *Bass* ist die tiefe Stimme."},
    "it/lungo": {"anecdote": "A *caffè lungo* is a 'long' espresso made with more water."},
    "it/corto": {"mnemonic": "(de) *corto* = kurz, beide von lateinisch *curtus*."},
    "it/caldo": {"mnemonic": "False friend: *caldo* = warm, not cold! The C on an Italian tap means hot water."},
    "it/freddo": {"mnemonic": "The F on an Italian tap means cold water."},
    "it/felice": {"mnemonic": "Like the name Felix, 'the happy, lucky one'."},
    "it/veloce": {"mnemonic": "English *velocity*: speed."},
    "it/lento": {"anecdote": "In music, *lento* means 'slowly'."},
    "it/ricco": {"anecdote": "A Germanic loanword, related to German *reich*."},
    "it/povero": {"mnemonic": "English *poverty*: being poor."},
    "it/forte": {"anecdote": "In music *forte* means loud; the *pianoforte* can play soft and loud."},
    # Italian numbers
    "it/zero": {"anecdote": "From Arabic *sifr*; Fibonacci of Pisa wrote it as *zephirum* when he brought Arabic numerals to Europe."},
    "it/due": {"mnemonic": "(de) Ein *Duo* oder *Duett* sind zwei."},
    "it/cinque": {"anecdote": "*Cinquecento* means the 16th century (the 1500s), and it is also the Fiat 500."},
    "it/sei": {"mnemonic": "*sei* is both 'six' and 'you are' (*tu sei*)."},
    "it/sette": {"mnemonic": "(de) *Sept*ember war im alten römischen Kalender der siebte Monat."},
    "it/otto": {"mnemonic": "(de) Aus -cht wird -tt: acht → *otto*, Nacht → *notte*."},
    "it/nove": {"anecdote": "*Novembre* was the ninth month of the old Roman calendar."},
    "it/dieci": {"anecdote": "*Dicembre* was the tenth month of the old Roman calendar."},
    "it/undici": {"mnemonic": "From 11 to 16 the unit comes first: *un-dici, do-dici, … se-dici*."},
    "it/diciassette": {"mnemonic": "From 17 on the ten comes first: *dici-assette, dici-otto, dici-annove*."},
    "it/venti": {"mnemonic": "*venti* is 'twenty', but also the plural of *vento*, 'winds'."},
    "it/cento": {"mnemonic": "(de) *Pro*zent = *per cento*, von hundert."},
    # Italian phrases
    "it/ciao": {"anecdote": "*ciao* comes from Venetian *s-ciào vostro*, 'your servant'."},
    "it/buonasera": {"anecdote": "Italians switch to *buonasera* surprisingly early, often right after lunch."},
    "it/buonanotte": {"mnemonic": "Only for going to bed or leaving late at night, never as a greeting."},
    "it/arrivederci": {"mnemonic": "(de) Wörtlich 'bis wir uns wiedersehen', wie *Auf Wiedersehen*."},
    "it/grazie": {"mnemonic": "(de) *Grazie* ist Anmut; von lateinisch *gratia* kommt auch *gratis*."},
    "it/prego": {"anecdote": "Literally 'I pray' (*pregare*); it also means 'please, go ahead'."},
    "it/scusi": {"mnemonic": "*scusi* is formal (Lei), *scusa* is informal (tu)."},
    "it/mi-dispiace": {"mnemonic": "Literally 'it displeases me', the opposite of *mi piace*."},
    "it/mi-chiamo-marco": {"mnemonic": "Literally 'I call myself Marco' (*chiamarsi*)."},
    "it/non-capisco": {"mnemonic": "(de) Ich kapiere nicht."},
    "it/si": {"mnemonic": "The accent matters: *sì* = yes, *si* = oneself."},
    "it/vorrei": {"mnemonic": "(de) Konditional von *volere*, wie 'ich möchte'."},
    "it/piacere": {"anecdote": "Short for *piacere di conoscerti*, 'a pleasure to meet you'."},
    "it/che-ore-sono": {"mnemonic": "Plural, because hours are plural: *sono le tre*; only *è l'una* is singular."},
    "it/il-conto-per-favore": {"mnemonic": "(de) Der *conto* belastet dein Konto."},
    # Italian forms
    "it/essere.pres": {"mnemonic": "*sono* means both 'I am' and 'they are'."},
    "it/avere.pres": {"anecdote": "The silent h of *ho, hai, ha, hanno* only tells them apart from *o* (or), *ai* (to the), *a* (to) and *anno* (year)."},
    "it/andare.pres": {"mnemonic": "*vado, vai, va, vanno* look like a different verb, because they are: Latin *vadere*."},
    "it/dare.pres": {"mnemonic": "*dà* (gives) has an accent to tell it apart from the preposition *da*."},
    "it/uscire.pres": {"mnemonic": "u turns into e when stressed: *esco, esci, esce, escono*, but *usciamo, uscite*."},
}


def add_memory(space: str, items: list[dict]) -> None:
    keys = {item["key"] for item in items}
    for ref in MEMORY:
        prefix, key = ref.split("/", 1)
        if prefix == space and key not in keys:
            raise ValueError(f"MEMORY entry for unknown item {ref}")
    for item in items:
        item["attrs"].update(MEMORY.get(f"{space}/{item['key']}", {}))


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
    add_memory("el", items)
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
    add_memory("it", list(items.values()))
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
