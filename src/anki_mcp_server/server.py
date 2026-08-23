from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import anki.collection  # noqa: F401 - Required before other anki imports in Python 3.14
from anki.cards import CardId
from anki.collection import AddNoteRequest, Collection
from anki.decks import DeckId
from anki.errors import AnkiError, NotFoundError
from anki.exporting import AnkiPackageExporter
from anki.notes import NoteId
from mcp.server import MCPServer

from anki_mcp_server.collection import get_collection
from anki_mcp_server.io_utils import (
    format_telemetry,
    make_response,
    read_json_file,
    write_tool_output,
)

server = MCPServer(
    name="anki-mcp-server",
    instructions="Universal File-Based I/O MCP Server for managing Anki flashcards, decks, notetypes, tags, media, and search.",
    version="0.2.0",
)

CARD_QUEUE_NAMES: dict[int, str] = {
    -3: "user_buried",
    -2: "sched_buried",
    -1: "suspended",
    0: "new",
    1: "learning",
    2: "review",
    3: "day_learning",
    4: "preview",
}

CARD_TYPE_NAMES: dict[int, str] = {
    0: "new",
    1: "learning",
    2: "review",
    3: "relearning",
}


# ============================================================================
# Internal Resolution & Construction Helpers
# ============================================================================


def _resolve_card_ids(
    col: Collection,
    card_ids: list[int] | None = None,
    note_ids: list[int] | None = None,
    query: str | None = None,
    input_file: str | None = None,
) -> list[CardId]:
    """Extract and validate a deduplicated list of CardIds from explicit IDs, note IDs, search queries, or input files."""
    target_cids: set[int] = set()

    if input_file:
        file_data = read_json_file(input_file)
        if isinstance(file_data, dict):
            card_ids = card_ids or file_data.get("card_ids")
            note_ids = note_ids or file_data.get("note_ids")
            query = query or file_data.get("query")
        elif isinstance(file_data, list):
            card_ids = card_ids or file_data

    if card_ids:
        target_cids.update(card_ids)

    if note_ids:
        for nid in note_ids:
            try:
                note = col.get_note(NoteId(nid))
                target_cids.update(note.card_ids())
            except (AnkiError, NotFoundError, KeyError):
                continue

    if query:
        target_cids.update(col.find_cards(query))

    if not target_cids:
        raise ValueError("No cards specified or found matching the criteria.")

    return [CardId(cid) for cid in target_cids]


def _resolve_note_ids(
    note_ids: list[int] | None = None,
    input_file: str | None = None,
) -> list[NoteId]:
    """Extract and validate a list of NoteIds from an argument list or input JSON file."""
    if input_file:
        file_data = read_json_file(input_file)
        if isinstance(file_data, list):
            note_ids = note_ids or file_data
        elif isinstance(file_data, dict):
            note_ids = note_ids or file_data.get("note_ids")

    if not note_ids:
        raise ValueError("Must provide 'note_ids' directly or inside 'input_file'.")

    return [NoteId(nid) for nid in note_ids]


def _build_note(
    col: Collection,
    data: dict[str, Any],
    default_deck: str | None = None,
    default_suspended: bool = False,
) -> tuple[AddNoteRequest, bool]:
    """Instantiate and populate an AddNoteRequest and suspension flag from a note specification dictionary."""
    deck_name = data.get("deck_name") or data.get("deck") or default_deck
    if not deck_name:
        raise ValueError("Must specify 'deck_name' for note.")

    deck_id = col.decks.id(deck_name)
    is_cloze = bool(data.get("is_cloze", False))
    notetype_name = data.get("notetype_name") or data.get("notetype")

    if notetype_name:
        notetype = col.models.by_name(notetype_name)
        if not notetype:
            raise ValueError(f"Notetype '{notetype_name}' not found in collection.")
    elif is_cloze:
        notetype = col.models.by_name("Cloze")
        if not notetype:
            raise ValueError("Stock 'Cloze' notetype not found in collection.")
    else:
        notetype = col.models.by_name("Basic")
        if not notetype:
            raise ValueError("Stock 'Basic' notetype not found in collection.")

    note = col.new_note(notetype)
    fields = data.get("fields")
    is_model_cloze = notetype.get("type") == 1

    if fields:
        for f_name, f_val in fields.items():
            if f_name in note:
                note[f_name] = str(f_val)
            else:
                raise ValueError(
                    f"Field '{f_name}' does not exist on notetype '{notetype['name']}'. "
                    f"Available fields: {col.models.field_names(notetype)}"
                )
    elif is_model_cloze or is_cloze:
        text = data.get("text") or data.get("front", "")
        if not text:
            raise ValueError(
                "Cloze note payload must contain non-empty 'text' or 'front'."
            )
        note["Text"] = text
        if "Extra" in note:
            note["Extra"] = data.get("extra") or data.get("back", "")
    else:
        field_names = col.models.field_names(notetype)
        front = data.get("front", "")
        back = data.get("back", "")
        if len(field_names) >= 2:
            note[field_names[0]] = front
            note[field_names[1]] = back
        elif len(field_names) == 1:
            note[field_names[0]] = front
        else:
            raise ValueError(f"Notetype '{notetype['name']}' has no fields.")

    note.tags = list(data.get("tags") or [])
    suspended = bool(data.get("suspended", default_suspended))

    return AddNoteRequest(note=note, deck_id=deck_id), suspended


# ============================================================================
# Deck Management Tools
# ============================================================================


@server.tool()
def list_decks(output_file: str | None = None) -> dict[str, Any]:
    """List all decks in the Anki collection with their IDs and card counts."""
    with get_collection() as col:
        full_decks = [
            {
                "id": entry.id,
                "name": entry.name,
                "card_count": col.decks.card_count(
                    dids=entry.id, include_subdecks=True
                ),
            }
            for entry in col.decks.all_names_and_ids()
        ]
        return make_response(
            operation="list_decks",
            payload=full_decks,
            summary={
                "deck_count": len(full_decks),
                "total_cards": sum(d["card_count"] for d in full_decks),
                "sample_decks": [d["name"] for d in full_decks[:5]],
            },
            output_file=output_file,
        )


@server.tool()
def create_deck(deck_name: str, output_file: str | None = None) -> dict[str, Any]:
    """Create a new deck or subdeck (e.g. 'Computer Science::Algorithms')."""
    with get_collection() as col:
        deck_id = col.decks.id(deck_name)
        return make_response(
            operation="create_deck",
            payload={"status": "success", "deck_id": deck_id, "deck_name": deck_name},
            summary={"deck_id": deck_id, "deck_name": deck_name},
            output_file=output_file,
        )


@server.tool()
def delete_deck(
    deck_id: int | None = None,
    deck_name: str | None = None,
    output_file: str | None = None,
) -> dict[str, Any]:
    """Delete a deck and all cards contained within it by deck ID or deck name."""
    with get_collection() as col:
        if deck_name and not deck_id:
            resolved_id = col.decks.id_for_name(deck_name)
            if not resolved_id:
                raise ValueError(f"Deck with name '{deck_name}' not found.")
            deck_id = int(resolved_id)

        if not deck_id:
            raise ValueError("Must provide either deck_id or deck_name.")

        col.decks.remove([DeckId(deck_id)])
        return make_response(
            operation="delete_deck",
            payload={"status": "success", "deleted_deck_id": deck_id},
            summary={"deleted_deck_id": deck_id},
            output_file=output_file,
        )


@server.tool()
def rename_deck(
    deck_id: int, new_name: str, output_file: str | None = None
) -> dict[str, Any]:
    """Rename an existing deck (and its child subdecks) by deck ID."""
    with get_collection() as col:
        deck = col.decks.get(DeckId(deck_id))
        if not deck:
            raise ValueError(f"Deck with ID {deck_id} not found.")
        old_name = deck["name"]
        col.decks.rename(DeckId(deck_id), new_name)
        return make_response(
            operation="rename_deck",
            payload={
                "status": "success",
                "deck_id": deck_id,
                "old_name": old_name,
                "new_name": new_name,
            },
            summary={"deck_id": deck_id, "old_name": old_name, "new_name": new_name},
            output_file=output_file,
        )


@server.tool()
def change_deck(
    target_deck_name: str | None = None,
    card_ids: list[int] | None = None,
    note_ids: list[int] | None = None,
    query: str | None = None,
    input_file: str | None = None,
    output_file: str | None = None,
) -> dict[str, Any]:
    """Move cards to a target deck by card IDs, note IDs, search query, or input file."""
    if input_file and not target_deck_name:
        file_data = read_json_file(input_file)
        if isinstance(file_data, dict):
            target_deck_name = file_data.get("target_deck_name") or file_data.get(
                "deck_name"
            )

    if not target_deck_name:
        raise ValueError(
            "Must provide 'target_deck_name' directly or inside 'input_file'."
        )

    with get_collection() as col:
        cids = _resolve_card_ids(
            col,
            card_ids=card_ids,
            note_ids=note_ids,
            query=query,
            input_file=input_file,
        )
        target_deck_id = col.decks.id(target_deck_name)
        col.set_deck(cids, target_deck_id)

        return make_response(
            operation="change_deck",
            payload={
                "status": "success",
                "target_deck_name": target_deck_name,
                "target_deck_id": target_deck_id,
                "cards_moved": len(cids),
                "card_ids": [int(c) for c in cids],
            },
            summary={
                "target_deck_name": target_deck_name,
                "cards_moved": len(cids),
                "sample_card_ids": [int(c) for c in cids[:5]],
            },
            output_file=output_file,
        )


# ============================================================================
# Media Management Tools
# ============================================================================


@server.tool()
def store_media_file(
    source_path: str,
    target_name: str | None = None,
) -> dict[str, Any]:
    """Store a media file (image, diagram, audio) directly from local disk into Anki's media storage."""
    p = Path(source_path).expanduser().resolve()
    if not p.is_file():
        raise FileNotFoundError(f"Media file not found at: {source_path}")

    desired_name = target_name or p.name

    with get_collection() as col:
        with open(p, "rb") as f:
            file_bytes = f.read()
        stored_name = col.media.write_data(desired_name, file_bytes)

        return format_telemetry(
            operation="store_media_file",
            summary={
                "filename": stored_name,
                "size_bytes": len(file_bytes),
                "html_embed": f'<img src="{stored_name}">',
                "markdown_embed": f"![{stored_name}]({stored_name})",
            },
        )


# ============================================================================
# Card State Control Tools
# ============================================================================


@server.tool()
def suspend_cards(
    card_ids: list[int] | None = None,
    note_ids: list[int] | None = None,
    query: str | None = None,
    input_file: str | None = None,
    output_file: str | None = None,
) -> dict[str, Any]:
    """Suspend cards from active review queues by card IDs, note IDs, search query, or input file."""
    with get_collection() as col:
        cids = _resolve_card_ids(
            col,
            card_ids=card_ids,
            note_ids=note_ids,
            query=query,
            input_file=input_file,
        )
        col.sched.suspend_cards(cids)
        return make_response(
            operation="suspend_cards",
            payload={
                "status": "success",
                "cards_suspended": len(cids),
                "card_ids": [int(c) for c in cids],
            },
            summary={
                "cards_suspended": len(cids),
                "sample_card_ids": [int(c) for c in cids[:5]],
            },
            output_file=output_file,
        )


@server.tool()
def unsuspend_cards(
    card_ids: list[int] | None = None,
    note_ids: list[int] | None = None,
    query: str | None = None,
    input_file: str | None = None,
    output_file: str | None = None,
) -> dict[str, Any]:
    """Unsuspend cards back into active review queues by card IDs, note IDs, search query, or input file."""
    with get_collection() as col:
        cids = _resolve_card_ids(
            col,
            card_ids=card_ids,
            note_ids=note_ids,
            query=query,
            input_file=input_file,
        )
        col.sched.unsuspend_cards(cids)
        return make_response(
            operation="unsuspend_cards",
            payload={
                "status": "success",
                "cards_unsuspended": len(cids),
                "card_ids": [int(c) for c in cids],
            },
            summary={
                "cards_unsuspended": len(cids),
                "sample_card_ids": [int(c) for c in cids[:5]],
            },
            output_file=output_file,
        )


# ============================================================================
# Notetype (Model) Tools
# ============================================================================


@server.tool()
def list_notetypes(output_file: str | None = None) -> dict[str, Any]:
    """List all available notetypes (models) in the collection, their fields, and types."""
    with get_collection() as col:

        def _format_nt(entry: Any) -> dict[str, Any]:
            model = col.models.get(entry.id)
            fields = col.models.field_names(model) if model else []
            is_cloze = (model.get("type") == 1) if model else False
            return {
                "id": entry.id,
                "name": entry.name,
                "fields": fields,
                "type": "cloze" if is_cloze else "standard",
            }

        notetypes = [_format_nt(entry) for entry in col.models.all_names_and_ids()]
        return make_response(
            operation="list_notetypes",
            payload=notetypes,
            summary={
                "notetype_count": len(notetypes),
                "notetype_names": [nt["name"] for nt in notetypes],
            },
            output_file=output_file,
        )


@server.tool()
def get_notetype_info(
    notetype_name: str, output_file: str | None = None
) -> dict[str, Any]:
    """Get detailed schema information about a specific notetype."""
    with get_collection() as col:
        model = col.models.by_name(notetype_name)
        if not model:
            raise ValueError(f"Notetype '{notetype_name}' not found.")

        payload = {
            "id": model["id"],
            "name": model["name"],
            "fields": col.models.field_names(model),
            "templates": [t.get("name", "") for t in model.get("tmpls", [])],
            "css": model.get("css", ""),
            "type": "cloze" if model.get("type") == 1 else "standard",
        }
        return make_response(
            operation="get_notetype_info",
            payload=payload,
            summary={
                "id": model["id"],
                "name": model["name"],
                "fields": payload["fields"],
                "templates": payload["templates"],
                "type": payload["type"],
            },
            prefix=f"notetype_{notetype_name}",
            output_file=output_file,
        )


# ============================================================================
# Card & Note Creation Tools (Strict File-Based)
# ============================================================================


@server.tool()
def add_note(
    input_file: str,
    deck_name: str | None = None,
    output_file: str | None = None,
) -> dict[str, Any]:
    """Create a new flashcard note from a JSON file payload."""
    data = read_json_file(input_file)
    if not isinstance(data, dict):
        raise TypeError(f"Input file '{input_file}' must contain a JSON object.")

    with get_collection() as col:
        req, suspended = _build_note(col, data, default_deck=deck_name)
        col.add_note(req.note, req.deck_id)

        card_ids = list(req.note.card_ids())
        if suspended and card_ids:
            col.sched.suspend_cards(card_ids)

        deck = col.decks.get(req.deck_id)
        deck_title = deck["name"] if deck else str(req.deck_id)

        return make_response(
            operation="add_note",
            payload={
                "status": "success",
                "note_id": req.note.id,
                "deck_name": deck_title,
                "deck_id": req.deck_id,
                "notetype_name": req.note.note_type()["name"],
                "tags": list(req.note.tags),
                "fields": dict(req.note.items()),
                "cards_generated": len(card_ids),
                "card_ids": card_ids,
                "suspended": suspended,
            },
            summary={
                "note_id": req.note.id,
                "deck_name": deck_title,
                "card_ids": card_ids,
                "tags": list(req.note.tags),
                "suspended": suspended,
            },
            prefix=f"add_note_{req.note.id}",
            output_file=output_file,
        )


@server.tool()
def add_cloze_note(
    input_file: str,
    deck_name: str | None = None,
    output_file: str | None = None,
) -> dict[str, Any]:
    """Create a Cloze deletion flashcard (fill-in-the-blank style) from a JSON file payload."""
    data = read_json_file(input_file)
    if not isinstance(data, dict):
        raise TypeError(f"Input file '{input_file}' must contain a JSON object.")

    data.setdefault("notetype_name", "Cloze")
    data["is_cloze"] = True

    with get_collection() as col:
        req, suspended = _build_note(col, data, default_deck=deck_name)
        col.add_note(req.note, req.deck_id)

        card_ids = list(req.note.card_ids())
        if suspended and card_ids:
            col.sched.suspend_cards(card_ids)

        deck = col.decks.get(req.deck_id)
        deck_title = deck["name"] if deck else str(req.deck_id)

        return make_response(
            operation="add_cloze_note",
            payload={
                "status": "success",
                "note_id": req.note.id,
                "deck_name": deck_title,
                "deck_id": req.deck_id,
                "tags": list(req.note.tags),
                "fields": dict(req.note.items()),
                "cards_generated": len(card_ids),
                "card_ids": card_ids,
                "suspended": suspended,
            },
            summary={
                "note_id": req.note.id,
                "deck_name": deck_title,
                "card_ids": card_ids,
                "tags": list(req.note.tags),
                "suspended": suspended,
            },
            prefix=f"add_cloze_note_{req.note.id}",
            output_file=output_file,
        )


@server.tool()
def add_notes_batch(
    input_file: str,
    output_file: str | None = None,
) -> dict[str, Any]:
    """Add multiple flashcard notes in a single high-throughput batch operation from a JSON file."""
    raw = read_json_file(input_file)
    if isinstance(raw, dict):
        notes_list = raw.get("notes") or raw.get("cards")
        if not isinstance(notes_list, list):
            raise TypeError(
                f"JSON object in '{input_file}' must contain a 'notes' list."
            )
        default_deck = raw.get("deck_name") or raw.get("deck")
        default_suspended = bool(raw.get("suspended", False))
    elif isinstance(raw, list):
        notes_list = raw
        default_deck = None
        default_suspended = False
    else:
        raise TypeError(
            f"Input file '{input_file}' must contain a JSON array or object with 'notes'."
        )

    with get_collection() as col:
        requests: list[AddNoteRequest] = []
        suspensions: list[bool] = []

        for item in notes_list:
            req, suspended = _build_note(
                col,
                item,
                default_deck=default_deck,
                default_suspended=default_suspended,
            )
            requests.append(req)
            suspensions.append(suspended)

        col.add_notes(requests)

        cards_to_suspend: list[CardId] = []
        for req, should_suspend in zip(requests, suspensions):
            if should_suspend:
                cards_to_suspend.extend(req.note.card_ids())

        if cards_to_suspend:
            col.sched.suspend_cards(cards_to_suspend)

        created = [
            {
                "note_id": req.note.id,
                "deck_id": req.deck_id,
                "tags": list(req.note.tags),
                "fields": dict(req.note.items()),
                "cards_generated": len(req.note.cards()),
                "card_ids": list(req.note.card_ids()),
            }
            for req in requests
        ]

        return make_response(
            operation="add_notes_batch",
            payload={
                "status": "success",
                "total_created": len(created),
                "notes": created,
            },
            summary={
                "total_created": len(created),
                "total_cards": sum(n["cards_generated"] for n in created),
                "sample_note_ids": [n["note_id"] for n in created[:5]],
            },
            prefix="add_notes_batch",
            output_file=output_file,
        )


# ============================================================================
# Note Inspection & Update Tools
# ============================================================================


@server.tool()
def get_note(note_id: int, output_file: str | None = None) -> dict[str, Any]:
    """Retrieve complete information about a note by its ID."""
    with get_collection() as col:
        note = col.get_note(NoteId(note_id))
        cards = note.cards()
        deck = col.decks.get(cards[0].did) if cards else None
        deck_name = deck.get("name") if deck else None

        payload = {
            "note_id": note.id,
            "guid": note.guid,
            "notetype_id": note.mid,
            "deck_name": deck_name,
            "tags": list(note.tags),
            "fields": dict(note.items()),
            "card_ids": list(note.card_ids()),
            "cards_count": len(cards),
            "modified_time": note.mod,
        }
        return make_response(
            operation="get_note",
            payload=payload,
            summary={
                "note_id": note.id,
                "deck_name": deck_name,
                "notetype_id": note.mid,
                "tags": list(note.tags),
                "field_names": list(note.keys()),
                "cards_count": len(cards),
            },
            prefix=f"get_note_{note.id}",
            output_file=output_file,
        )


@server.tool()
def update_note(
    note_id: int,
    input_file: str,
    output_file: str | None = None,
) -> dict[str, Any]:
    """Update fields and/or tags of an existing note from a JSON file."""
    data = read_json_file(input_file)
    if not isinstance(data, dict):
        raise TypeError(f"Input file '{input_file}' must contain a JSON object.")

    fields = data.get("fields")
    tags = data.get("tags")

    with get_collection() as col:
        note = col.get_note(NoteId(note_id))

        if fields:
            for field_name, value in fields.items():
                if field_name in note:
                    note[field_name] = value
                else:
                    raise ValueError(
                        f"Field '{field_name}' not found on note {note_id}."
                    )

        if tags is not None:
            note.tags = list(tags)

        col.update_note(note)

        return make_response(
            operation="update_note",
            payload={
                "status": "success",
                "note_id": note.id,
                "tags": list(note.tags),
                "fields": dict(note.items()),
            },
            summary={
                "note_id": note.id,
                "updated_fields": list(fields.keys()) if fields else [],
                "tags": list(note.tags),
            },
            prefix=f"update_note_{note.id}",
            output_file=output_file,
        )


@server.tool()
def delete_notes(
    note_ids: list[int] | None = None,
    input_file: str | None = None,
    output_file: str | None = None,
) -> dict[str, Any]:
    """Delete notes (and all cards generated from them) by their Note IDs or from a JSON file list."""
    nids = _resolve_note_ids(note_ids=note_ids, input_file=input_file)

    with get_collection() as col:
        col.remove_notes(nids)
        return make_response(
            operation="delete_notes",
            payload={
                "status": "success",
                "deleted_count": len(nids),
                "deleted_note_ids": [int(nid) for nid in nids],
            },
            summary={
                "deleted_count": len(nids),
                "sample_deleted_ids": [int(nid) for nid in nids[:5]],
            },
            output_file=output_file,
        )


# ============================================================================
# Search Tools
# ============================================================================


@server.tool()
def search_notes(
    query: str, limit: int = 500, output_file: str | None = None
) -> dict[str, Any]:
    """Search notes using Anki browser syntax, writing full matched cards/fields to disk."""
    with get_collection() as col:
        note_ids = col.find_notes(query)[:limit]
        results = []
        for nid in note_ids:
            try:
                note = col.get_note(nid)
                cards = note.cards()
                deck = col.decks.get(cards[0].did) if cards else None
                results.append(
                    {
                        "note_id": note.id,
                        "deck_name": deck.get("name") if deck else None,
                        "tags": list(note.tags),
                        "fields": dict(note.items()),
                    }
                )
            except (AnkiError, NotFoundError, KeyError):
                continue

        return make_response(
            operation="search_notes",
            payload=results,
            summary={
                "query": query,
                "total_matches": len(results),
                "sample_note_ids": [r["note_id"] for r in results[:5]],
            },
            output_file=output_file,
        )


@server.tool()
def search_cards(
    query: str, limit: int = 500, output_file: str | None = None
) -> dict[str, Any]:
    """Search cards using Anki browser syntax, returning card queue status, due dates, and intervals to disk."""
    with get_collection() as col:
        card_ids = col.find_cards(query)[:limit]
        results = []
        for cid in card_ids:
            try:
                card = col.get_card(CardId(cid))
                deck = col.decks.get(card.did)
                results.append(
                    {
                        "card_id": card.id,
                        "note_id": card.nid,
                        "deck_name": deck.get("name") if deck else None,
                        "queue": CARD_QUEUE_NAMES.get(card.queue, str(card.queue)),
                        "type": CARD_TYPE_NAMES.get(card.type, str(card.type)),
                        "due": card.due,
                        "interval_days": card.ivl,
                        "reps": card.reps,
                        "lapses": card.lapses,
                    }
                )
            except (AnkiError, NotFoundError, KeyError):
                continue

        return make_response(
            operation="search_cards",
            payload=results,
            summary={
                "query": query,
                "total_matches": len(results),
                "sample_card_ids": [r["card_id"] for r in results[:5]],
            },
            output_file=output_file,
        )


# ============================================================================
# Tag Management Tools
# ============================================================================


@server.tool()
def list_tags(output_file: str | None = None) -> dict[str, Any]:
    """List all unique tags across the collection, writing full tag array to disk."""
    with get_collection() as col:
        all_tags = col.tags.all()
        return make_response(
            operation="list_tags",
            payload=all_tags,
            summary={
                "tag_count": len(all_tags),
                "sample_tags": all_tags[:10],
            },
            output_file=output_file,
        )


@server.tool()
def add_tags_to_notes(
    note_ids: list[int] | None = None,
    tags: list[str] | None = None,
    input_file: str | None = None,
    output_file: str | None = None,
) -> dict[str, Any]:
    """Add one or more tags in bulk to notes from argument lists or a JSON file."""
    if input_file and tags is None:
        file_data = read_json_file(input_file)
        if isinstance(file_data, dict):
            tags = file_data.get("tags")

    nids = _resolve_note_ids(note_ids=note_ids, input_file=input_file)
    if not tags:
        raise ValueError("Must provide 'tags' directly or in 'input_file'.")

    with get_collection() as col:
        col.tags.bulk_add(nids, " ".join(tags))
        return make_response(
            operation="add_tags_to_notes",
            payload={
                "status": "success",
                "notes_affected": len(nids),
                "note_ids": [int(nid) for nid in nids],
                "tags_added": tags,
            },
            summary={
                "notes_affected": len(nids),
                "tags_added": tags,
            },
            output_file=output_file,
        )


@server.tool()
def remove_tags_from_notes(
    note_ids: list[int] | None = None,
    tags: list[str] | None = None,
    input_file: str | None = None,
    output_file: str | None = None,
) -> dict[str, Any]:
    """Remove one or more tags in bulk from notes from argument lists or a JSON file."""
    if input_file and tags is None:
        file_data = read_json_file(input_file)
        if isinstance(file_data, dict):
            tags = file_data.get("tags")

    nids = _resolve_note_ids(note_ids=note_ids, input_file=input_file)
    if not tags:
        raise ValueError("Must provide 'tags' directly or in 'input_file'.")

    with get_collection() as col:
        col.tags.bulk_remove(nids, " ".join(tags))
        return make_response(
            operation="remove_tags_from_notes",
            payload={
                "status": "success",
                "notes_affected": len(nids),
                "note_ids": [int(nid) for nid in nids],
                "tags_removed": tags,
            },
            summary={
                "notes_affected": len(nids),
                "tags_removed": tags,
            },
            output_file=output_file,
        )


# ============================================================================
# Statistics & Export Tools
# ============================================================================


@server.tool()
def get_collection_stats(output_file: str | None = None) -> dict[str, Any]:
    """Get collection statistics (total notes, cards, new/due cards, deck breakdown)."""
    with get_collection() as col:
        decks_breakdown = [
            {
                "id": entry.id,
                "name": entry.name,
                "cards": col.decks.card_count(dids=entry.id, include_subdecks=True),
            }
            for entry in col.decks.all_names_and_ids()
        ]
        return make_response(
            operation="get_collection_stats",
            payload={
                "total_notes": col.db.scalar("select count() from notes"),
                "total_cards": col.db.scalar("select count() from cards"),
                "new_cards": len(col.find_cards("is:new")),
                "due_cards": len(col.find_cards("is:due")),
                "decks": decks_breakdown,
            },
            summary={
                "total_notes": col.db.scalar("select count() from notes"),
                "total_cards": col.db.scalar("select count() from cards"),
                "new_cards": len(col.find_cards("is:new")),
                "due_cards": len(col.find_cards("is:due")),
                "deck_count": len(decks_breakdown),
            },
            output_file=output_file,
        )


@server.tool()
def export_deck(
    deck_name: str,
    target_path: str,
    format: str = "apkg",
    include_media: bool = True,
) -> dict[str, Any]:
    """Export a deck to an Anki package (.apkg), full collection package (.colpkg), or structured JSON file."""
    dest = Path(target_path).expanduser().resolve()
    dest.parent.mkdir(parents=True, exist_ok=True)
    fmt = format.lower().strip(".")

    with get_collection() as col:
        if fmt == "apkg":
            deck_id = col.decks.id_for_name(deck_name)
            if not deck_id:
                raise ValueError(f"Deck '{deck_name}' not found in collection.")

            exporter = AnkiPackageExporter(col)
            exporter.did = DeckId(deck_id)
            exporter.includeMedia = include_media
            exporter.exportInto(str(dest))

        elif fmt == "colpkg":
            col.export_collection_package(
                out_path=str(dest), include_media=include_media, legacy=False
            )

        elif fmt == "json":
            deck_id = col.decks.id_for_name(deck_name)
            if not deck_id:
                raise ValueError(f"Deck '{deck_name}' not found in collection.")

            notes_data = [
                {
                    "note_id": n.id,
                    "tags": list(n.tags),
                    "fields": dict(n.items()),
                    "card_ids": list(n.card_ids()),
                }
                for n in (
                    col.get_note(nid) for nid in col.find_notes(f'deck:"{deck_name}"')
                )
            ]
            write_tool_output(notes_data, output_file=str(dest))

        else:
            raise ValueError(
                f"Unsupported export format '{format}'. Supported formats: 'apkg', 'colpkg', 'json'."
            )

        return format_telemetry(
            operation="export_deck",
            summary={
                "deck_name": deck_name,
                "format": fmt,
                "target_path": str(dest),
                "size_bytes": dest.stat().st_size if dest.exists() else 0,
            },
        )


# ============================================================================
# MCP Resources & Prompts
# ============================================================================


@server.resource("anki://decks")
def get_decks_resource() -> str:
    """Resource returning all Anki decks and their card counts as JSON."""
    with get_collection() as col:
        decks = [
            {
                "id": entry.id,
                "name": entry.name,
                "card_count": col.decks.card_count(
                    dids=entry.id, include_subdecks=True
                ),
            }
            for entry in col.decks.all_names_and_ids()
        ]
        return json.dumps(decks, indent=2)


@server.resource("anki://stats")
def get_stats_resource() -> str:
    """Resource returning collection overview and due statistics as JSON."""
    with get_collection() as col:
        stats = {
            "total_notes": col.db.scalar("select count() from notes"),
            "total_cards": col.db.scalar("select count() from cards"),
            "new_cards": len(col.find_cards("is:new")),
            "due_cards": len(col.find_cards("is:due")),
        }
        return json.dumps(stats, indent=2)


@server.prompt()
def flashcard_generator(
    topic: str,
    concept: str,
    deck_name: str | None = None,
    difficulty: str = "medium",
) -> str:
    """Prompt template for generating high-quality flashcards with LaTeX formulas, code, and structured tags."""
    target_deck = deck_name or topic.title()
    return f"""You are creating educational flashcards for Anki using the File-Based I/O format.

Topic: {topic}
Concept: {concept}
Target Deck: {target_deck}
Difficulty: {difficulty}

Guidelines:
1. Make the Question (Front) clear, unambiguous, and focused on a single atomic concept.
2. Provide a concise, comprehensive Answer (Back) with key intuition, examples, or derivation.
3. For mathematics/formulas, use LaTeX formatting:
   - Inline math: $...$
   - Display math: $$...$$
4. For code snippets, format with markdown code fences (e.g. ```python ... ```).
5. Apply relevant hierarchical tags:
   - `topic::{topic.lower().replace(" ", "-")}`
   - `difficulty::{difficulty.lower()}`
6. Save your card payload to a temporary JSON file before calling `add_note(input_file=...)`.
"""
