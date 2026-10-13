"""Knowledge profile helpers for the CLI: importing item files,
writing and restoring the JSON-lines export.

Item files sit next to the card decks in content/ and are detected
by a top-level "items" key:

    {"space": "it",                       # default space of the items
     "dirs": ["italian", "italian/a1"],   # directories (subjects) to create
     "items": [{"key": "parlare", "kind": "word", "label_md": "parlare",
                "gloss_md": "to speak", "dirs": ["italian/a1"],
                "links": [{"rel": "requires", "to": "present-are"}]}],
     "card_links": [{"card": "Translate to Italian: **to speak**",
                     "item": "parlare"}]}

Imports go through PUT /items/bulk (exact identity, idempotent), so
re-importing a file updates in place.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Callable, Iterable

from pauk.client import ApiError, Client

BULK = 500


def import_items(client: Client, data: dict, ensure_dirs: Callable[[list[str]], dict[str, int]], echo=print) -> dict:
    space = data.get("space")
    items = data["items"]
    paths = set(data.get("dirs", []))
    for item in items:
        paths.update(item.get("dirs", []))
    dir_ids = ensure_dirs(sorted(paths))

    bodies = []
    for item in items:
        body = dict(item)
        if space and "space" not in body:
            body["space"] = space
        body["dirs"] = [dir_ids[p] for p in item.get("dirs", [])]
        bodies.append(body)

    totals = {"created": 0, "updated": 0, "unchanged": 0}
    conflicts: list[dict] = []
    duplicates: list[dict] = []
    unresolved: list[dict] = []
    for start in range(0, len(bodies), BULK):
        result = client.bulk_items(bodies[start:start + BULK])
        for name in totals:
            totals[name] += result[name]
        conflicts += result["conflicts"]
        duplicates += result["possible_duplicates"]
        unresolved += result["unresolved_links"]

    linked = 0
    card_links = data.get("card_links", [])
    if card_links:
        by_question = {card["question_md"]: card["id"] for card in client.iter_cards()}
        for link in card_links:
            card_id = by_question.get(link["card"])
            if card_id is None:
                echo(f"[yellow]card not found, link skipped:[/yellow] {link['card']}")
                continue
            ref = link["item"] if "/" in link["item"] else f"{space}/{link['item']}"
            client.link_card_item(card_id, ref)
            linked += 1

    echo(
        f"items: {totals['created']} created, {totals['updated']} updated, "
        f"{totals['unchanged']} unchanged; {linked} card links"
    )
    for c in conflicts:
        echo(f"[yellow]kept teacher item[/yellow] {c['ref']}: '{c['existing_gloss']}' (import: '{c['import_gloss']}')")
    for d in duplicates:
        echo(f"[yellow]possible duplicate[/yellow] {d['ref']} ~ {d['similar']} (check with `pauk items dedup`)")
    for u in unresolved:
        echo(f"[yellow]unresolved link[/yellow] {u['from']} -{u['rel']}-> {u['to']}")
    return totals


def write_export(client: Client, path: Path) -> int:
    count = 0
    with path.open("w", encoding="utf-8", newline="\n") as f:
        for line in client.export_lines():
            f.write(line + "\n")
            count += 1
    return count


def restore_export(client: Client, path: Path, ensure_dirs: Callable[[list[str]], dict[str, int]], echo=print) -> dict:
    """Re-import an export: directories by path, items by ref, flags,
    then interactions by uuid (idempotent) with their amendments.
    Card links are not restored: card ids belong to the source
    database."""
    records = [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]
    header = records[0]
    if header.get("format") != "pauk-export" or header.get("version") != 1:
        raise ValueError(f"{path} is not a pauk export (version 1)")

    dirs = {r["id"]: r for r in records if r.get("type") == "dir"}
    dir_paths = {dir_id: _dir_path(dirs, dir_id) for dir_id in dirs}
    new_ids = ensure_dirs(sorted(set(dir_paths.values())))

    items = [r for r in records if r.get("type") == "item"]
    bodies = []
    for item in items:
        if item.get("merged_into"):
            continue  # merged items live on as aliases of their target
        body = {k: item[k] for k in ("space", "key", "kind", "label_md", "gloss_md", "body_md", "attrs", "priority", "level")}
        body["dirs"] = [new_ids[dir_paths[d]] for d in item.get("dirs", []) if d in dir_paths]
        body["links"] = [{"rel": l["rel"], "to": l["to"]} for l in item.get("links", [])]
        bodies.append(body)
    created = 0
    for start in range(0, len(bodies), BULK):
        created += client.bulk_items(bodies[start:start + BULK])["created"]
    for item in items:
        flags = item.get("flags")
        if flags and not item.get("merged_into") and (flags["status"] != "active" or flags["note"]):
            client.set_item_flags(item["ref"], flags["status"], flags["note"])

    recorded = 0
    for r in (r for r in records if r.get("type") == "interaction"):
        body = {k: r[k] for k in ("uuid", "occurred_at", "mode", "source", "session_id", "hinted",
                                  "prompt_md", "response_md", "feedback_md", "exercise", "response")
                if r.get(k) is not None}
        # merges are not replayed: evidence goes to the current item
        current = {i["origin"]: i["ref"] for i in r["items"]}
        body["items"] = [{"ref": i["ref"], "outcome": i["outcome"], **({"note": i["note"]} if i.get("note") else {})}
                         for i in r["items"]]
        if body["mode"] == "introduce":
            for i in body["items"]:
                i.pop("outcome", None)
        try:
            if client.record_interaction(body)["created"]:
                recorded += 1
                for a in r.get("amendments", []):
                    client.amend_interaction(r["uuid"], {"items": [{"ref": current.get(a["origin"], a["origin"]), "outcome": a["outcome"]}],
                                                         "reason": a["reason"], "by": a["by"]})
        except ApiError as e:
            echo(f"[yellow]interaction {r['uuid']} skipped:[/yellow] {e}")
    settings = next((r["values"] for r in records if r.get("type") == "settings"), None)
    if settings:
        client.update_settings(settings)
    echo(f"restored {created} new items, {recorded} new interactions")
    return {"items": created, "interactions": recorded}


def _dir_path(dirs: dict, dir_id: int, seen: frozenset = frozenset()) -> str:
    d = dirs[dir_id]
    parents = [p for p in d["parents"] if p in dirs and p not in seen]
    if not parents:
        return d["name"]
    return _dir_path(dirs, min(parents), seen | {dir_id}) + "/" + d["name"]


def print_profile(client: Client, summary: dict, next_items: dict, echo=print) -> None:
    levels = summary["by_mastery"]
    names = ["unseen", "introduced", "fragile", "learning", "known", "mastered"]
    coverage = "-" if summary["coverage"] is None else f"{summary['coverage']:.0%}"
    echo(f"items: {summary['items']} · coverage: {coverage} · due: {summary['due']}")
    echo(" · ".join(f"{names[i]} {levels[str(i)]}" for i in range(6)))
    _print_entries("review next", next_items["review"], echo)
    _print_entries("new next", next_items["new"], echo)


def _print_entries(title: str, entries: Iterable[dict], echo) -> None:
    entries = list(entries)
    if entries:
        echo(f"\n{title}:")
        for e in entries:
            echo(f"  {e['ref']}  {e['label_md']} — {e['gloss_md']}  ({e['reason']})")
