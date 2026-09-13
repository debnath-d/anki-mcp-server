from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Literal

CardState = Literal["suspended", "active"]
TagAction = Literal["add", "remove"]

import anki.collection  # noqa: F401 - Required before other anki imports in Python 3.14
from anki.cards import CardId
from anki.collection import Collection
from anki.decks import DeckId
from anki.errors import AnkiError, NotFoundError
from anki.exporting import AnkiPackageExporter
from anki.notes import NoteId
from mcp.server import MCPServer

from anki_mcp_server.collection import get_collection
from anki_mcp_server.io_utils import format_telemetry, write_tool_output
from anki_mcp_server.notes import ingest_notes
from anki_mcp_server.pipeline import execute_tool
from anki_mcp_server.selector import TargetSpec

INSTRUCTIONS_PATH = Path(__file__).parent / "instructions.md"
DEFAULT_INSTRUCTIONS = (
    "Universal File-Based I/O MCP Server for managing Anki flashcards, decks, "
    "notetypes, tags, media, and search."
)
INSTRUCTIONS = (
    INSTRUCTIONS_PATH.read_text(encoding="utf-8")
    if INSTRUCTIONS_PATH.is_file()
    else DEFAULT_INSTRUCTIONS
)

server = MCPServer(
    name="anki-mcp-server",
    instructions=INSTRUCTIONS,
    version="0.3.0",
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
# Deck Management Tools
# ============================================================================


@server.tool()
def list_decks(output_file: str | None = None) -> dict[str, Any]:
    """List all decks in the Anki collection with their IDs and card counts."""

    def action(col: Collection, _: Any) -> list[dict[str, Any]]:
        return [
            {
                "id": entry.id,
                "name": entry.name,
                "card_count": col.decks.card_count(
                    dids=DeckId(entry.id), include_subdecks=True
                ),
            }
            for entry in col.decks.all_names_and_ids()
        ]

    def summary_fn(data: list[dict[str, Any]]) -> dict[str, Any]:
        return {
            "deck_count": len(data),
            "total_cards": sum(d["card_count"] for d in data),
            "sample_decks": [d["name"] for d in data[:5]],
        }

    return execute_tool(
        operation="list_decks",
        action=action,
        output_file=output_file,
        summary_fn=summary_fn,
    )


@server.tool()
def create_deck(deck_name: str, output_file: str | None = None) -> dict[str, Any]:
    """Create a new deck or subdeck (e.g. 'Computer Science::Algorithms')."""

    def action(col: Collection, _: Any) -> dict[str, Any]:
        deck_id = col.decks.id(deck_name)
        if deck_id is None:
            raise ValueError(f"Could not find or create deck '{deck_name}'.")
        return {"deck_id": int(deck_id), "deck_name": deck_name}

    return execute_tool(
        operation="create_deck",
        action=action,
        output_file=output_file,
    )


@server.tool()
def delete_deck(
    deck_id: int | None = None,
    deck_name: str | None = None,
    output_file: str | None = None,
) -> dict[str, Any]:
    """Delete a deck and all cards contained within it by deck ID or deck name."""

    def action(col: Collection, _: Any) -> dict[str, Any]:
        nonlocal deck_id
        if deck_name and not deck_id:
            resolved_id = col.decks.id_for_name(deck_name)
            if not resolved_id:
                raise ValueError(f"Deck with name '{deck_name}' not found.")
            deck_id = int(resolved_id)

        if not deck_id:
            raise ValueError("Must provide either deck_id or deck_name.")

        col.decks.remove([DeckId(deck_id)])
        return {"deleted_deck_id": deck_id}

    return execute_tool(
        operation="delete_deck",
        action=action,
        output_file=output_file,
    )


@server.tool()
def rename_deck(
    deck_id: int, new_name: str, output_file: str | None = None
) -> dict[str, Any]:
    """Rename an existing deck (and its child subdecks) by deck ID."""

    def action(col: Collection, _: Any) -> dict[str, Any]:
        deck = col.decks.get(DeckId(deck_id))
        if not deck:
            raise ValueError(f"Deck with ID {deck_id} not found.")
        old_name = deck["name"]
        col.decks.rename(DeckId(deck_id), new_name)
        return {
            "deck_id": deck_id,
            "old_name": old_name,
            "new_name": new_name,
        }

    return execute_tool(
        operation="rename_deck",
        action=action,
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
    spec = TargetSpec(
        card_ids=card_ids, note_ids=note_ids, query=query, input_file=input_file
    )

    def action(col: Collection, _: Any) -> dict[str, Any]:
        deck_name = target_deck_name
        if spec.input_file and not deck_name:
            file_data = spec.get_file_payload()
            if isinstance(file_data, dict):
                deck_name = file_data.get("target_deck_name") or file_data.get(
                    "deck_name"
                )

        if not deck_name:
            raise ValueError(
                "Must provide 'target_deck_name' directly or inside 'input_file'."
            )

        cids = spec.resolve_card_ids(col)
        target_deck_id = col.decks.id(deck_name)
        if target_deck_id is None:
            raise ValueError(f"Target deck '{deck_name}' not found.")
        col.set_deck(cids, target_deck_id)

        return {
            "target_deck_name": deck_name,
            "target_deck_id": int(target_deck_id),
            "cards_moved": len(cids),
            "card_ids": [int(c) for c in cids],
        }

    return execute_tool(
        operation="change_deck",
        action=action,
        output_file=output_file,
    )


# ============================================================================
# Notetype (Model) Tools
# ============================================================================


@server.tool()
def list_notetypes(output_file: str | None = None) -> dict[str, Any]:
    """List all available notetypes (models) in the collection, their fields, and types."""

    def action(col: Collection, _: Any) -> list[dict[str, Any]]:
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

        return [_format_nt(entry) for entry in col.models.all_names_and_ids()]

    def summary_fn(data: list[dict[str, Any]]) -> dict[str, Any]:
        return {
            "notetype_count": len(data),
            "notetype_names": [nt["name"] for nt in data],
        }

    return execute_tool(
        operation="list_notetypes",
        action=action,
        output_file=output_file,
        summary_fn=summary_fn,
    )


@server.tool()
def get_notetype_info(
    notetype_name: str, output_file: str | None = None
) -> dict[str, Any]:
    """Get detailed schema information about a specific notetype."""

    def action(col: Collection, _: Any) -> dict[str, Any]:
        model = col.models.by_name(notetype_name)
        if not model:
            raise ValueError(f"Notetype '{notetype_name}' not found.")

        return {
            "id": model["id"],
            "name": model["name"],
            "fields": col.models.field_names(model),
            "templates": [t.get("name", "") for t in model.get("tmpls", [])],
            "css": model.get("css", ""),
            "type": "cloze" if model.get("type") == 1 else "standard",
        }

    def summary_fn(data: dict[str, Any]) -> dict[str, Any]:
        return {
            "id": data["id"],
            "name": data["name"],
            "fields": data["fields"],
            "templates": data["templates"],
            "type": data["type"],
        }

    return execute_tool(
        operation="get_notetype_info",
        action=action,
        prefix=f"notetype_{notetype_name}",
        output_file=output_file,
        summary_fn=summary_fn,
    )


# ============================================================================
# Consolidated Card & Note Ingestion Tools
# ============================================================================


@server.tool()
def add_notes(
    input_file: str,
    deck_name: str | None = None,
    output_file: str | None = None,
) -> dict[str, Any]:
    """Ingest one or more notes (single note, cloze deletion, or batch array) from a JSON file."""

    def action(col: Collection, payload: Any) -> list[dict[str, Any]]:
        ingested = ingest_notes(col, payload, default_deck=deck_name)
        return [note.to_dict() for note in ingested]

    def summary_fn(data: list[dict[str, Any]]) -> dict[str, Any]:
        return {
            "total_created": len(data),
            "total_cards": sum(n["cards_generated"] for n in data),
            "sample_note_ids": [n["note_id"] for n in data[:5]],
            "sample_decks": list({n["deck_name"] for n in data})[:5],
        }

    return execute_tool(
        operation="add_notes",
        action=action,
        input_file=input_file,
        output_file=output_file,
        summary_fn=summary_fn,
    )


# ============================================================================
# Note Inspection & Mutation Tools
# ============================================================================


@server.tool()
def get_note(note_id: int, output_file: str | None = None) -> dict[str, Any]:
    """Retrieve complete information about a note by its ID."""

    def action(col: Collection, _: Any) -> dict[str, Any]:
        note = col.get_note(NoteId(note_id))
        cards = note.cards()
        deck = col.decks.get(cards[0].did) if cards else None
        deck_name = deck.get("name") if deck else None

        return {
            "note_id": int(note.id),
            "guid": note.guid,
            "notetype_id": int(note.mid),
            "deck_name": deck_name,
            "tags": list(note.tags),
            "fields": dict(note.items()),
            "card_ids": [int(c) for c in note.card_ids()],
            "cards_count": len(cards),
            "modified_time": note.mod,
        }

    return execute_tool(
        operation="get_note",
        action=action,
        prefix=f"get_note_{note_id}",
        output_file=output_file,
    )


@server.tool()
def update_note(
    note_id: int,
    input_file: str,
    output_file: str | None = None,
) -> dict[str, Any]:
    """Update fields and/or tags of an existing note from a JSON file."""

    def action(col: Collection, data: Any) -> dict[str, Any]:
        if not isinstance(data, dict):
            raise TypeError(f"Input file '{input_file}' must contain a JSON object.")

        fields = data.get("fields")
        tags = data.get("tags")

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

        return {
            "note_id": int(note.id),
            "tags": list(note.tags),
            "fields": dict(note.items()),
            "updated_fields": list(fields.keys()) if fields else [],
        }

    return execute_tool(
        operation="update_note",
        action=action,
        input_file=input_file,
        prefix=f"update_note_{note_id}",
        output_file=output_file,
    )


@server.tool()
def delete_notes(
    note_ids: list[int] | None = None,
    input_file: str | None = None,
    output_file: str | None = None,
) -> dict[str, Any]:
    """Delete notes (and all cards generated from them) by their Note IDs or from a JSON file list."""
    spec = TargetSpec(note_ids=note_ids, input_file=input_file)

    def action(col: Collection, _: Any) -> dict[str, Any]:
        nids = spec.resolve_note_ids(col)
        col.remove_notes(nids)
        return {
            "deleted_count": len(nids),
            "deleted_note_ids": [int(nid) for nid in nids],
        }

    return execute_tool(
        operation="delete_notes",
        action=action,
        output_file=output_file,
    )


# ============================================================================
# Consolidated State & Tag Control Tools
# ============================================================================


@server.tool()
def set_card_state(
    state: CardState = "suspended",
    card_ids: list[int] | None = None,
    note_ids: list[int] | None = None,
    query: str | None = None,
    input_file: str | None = None,
    output_file: str | None = None,
) -> dict[str, Any]:
    """Set card review queue state ('suspended' or 'active') across target cards, notes, queries, or files."""
    spec = TargetSpec(
        card_ids=card_ids, note_ids=note_ids, query=query, input_file=input_file
    )

    def action(col: Collection, _: Any) -> dict[str, Any]:
        cids = spec.resolve_card_ids(col)
        norm_state = state.strip().lower()

        if norm_state in ("suspended", "suspend"):
            col.sched.suspend_cards(cids)
            resolved_state = "suspended"
        elif norm_state in ("active", "unsuspended", "unsuspend"):
            col.sched.unsuspend_cards(cids)
            resolved_state = "active"
        else:
            raise ValueError(
                f"Invalid card state '{state}'. Expected 'suspended' or 'active'."
            )

        return {
            "state": resolved_state,
            "cards_affected": len(cids),
            "card_ids": [int(c) for c in cids],
        }

    return execute_tool(
        operation="set_card_state",
        action=action,
        output_file=output_file,
    )


@server.tool()
def update_note_tags(
    action: TagAction = "add",
    tags: list[str] | None = None,
    note_ids: list[int] | None = None,
    input_file: str | None = None,
    output_file: str | None = None,
) -> dict[str, Any]:
    """Add or remove tags in bulk across notes specified directly or within a JSON payload file."""
    spec = TargetSpec(note_ids=note_ids, input_file=input_file)

    def run_action(col: Collection, _: Any) -> dict[str, Any]:
        target_tags = tags
        if spec.input_file and target_tags is None:
            file_data = spec.get_file_payload()
            if isinstance(file_data, dict):
                target_tags = file_data.get("tags")

        if not target_tags:
            raise ValueError("Must provide 'tags' directly or inside 'input_file'.")

        nids = spec.resolve_note_ids(col)
        norm_action = action.strip().lower()
        tag_str = " ".join(target_tags)

        if norm_action == "add":
            col.tags.bulk_add(nids, tag_str)
        elif norm_action == "remove":
            col.tags.bulk_remove(nids, tag_str)
        else:
            raise ValueError(
                f"Invalid tag action '{action}'. Expected 'add' or 'remove'."
            )

        return {
            "action": norm_action,
            "notes_affected": len(nids),
            "note_ids": [int(nid) for nid in nids],
            "tags": target_tags,
        }

    return execute_tool(
        operation="update_note_tags",
        action=run_action,
        output_file=output_file,
    )


# ============================================================================
# Search & Tag Inspection Tools
# ============================================================================


@server.tool()
def list_tags(output_file: str | None = None) -> dict[str, Any]:
    """List all unique tags across the collection, writing full tag array to disk."""

    def action(col: Collection, _: Any) -> list[str]:
        return col.tags.all()

    def summary_fn(data: list[str]) -> dict[str, Any]:
        return {
            "tag_count": len(data),
            "sample_tags": data[:10],
        }

    return execute_tool(
        operation="list_tags",
        action=action,
        output_file=output_file,
        summary_fn=summary_fn,
    )


@server.tool()
def search_notes(
    query: str, limit: int = 500, output_file: str | None = None
) -> dict[str, Any]:
    """Search notes using Anki browser syntax, writing full matched cards/fields to disk."""

    def action(col: Collection, _: Any) -> list[dict[str, Any]]:
        note_ids = col.find_notes(query)[:limit]
        results = []
        for nid in note_ids:
            try:
                note = col.get_note(nid)
                cards = note.cards()
                deck = col.decks.get(cards[0].did) if cards else None
                results.append(
                    {
                        "note_id": int(note.id),
                        "deck_name": deck.get("name") if deck else None,
                        "tags": list(note.tags),
                        "fields": dict(note.items()),
                    }
                )
            except (AnkiError, NotFoundError, KeyError):
                continue
        return results

    def summary_fn(data: list[dict[str, Any]]) -> dict[str, Any]:
        return {
            "query": query,
            "total_matches": len(data),
            "sample_note_ids": [r["note_id"] for r in data[:5]],
        }

    return execute_tool(
        operation="search_notes",
        action=action,
        output_file=output_file,
        summary_fn=summary_fn,
    )


@server.tool()
def search_cards(
    query: str, limit: int = 500, output_file: str | None = None
) -> dict[str, Any]:
    """Search cards using Anki browser syntax, returning card queue status, due dates, and intervals to disk."""

    def action(col: Collection, _: Any) -> list[dict[str, Any]]:
        card_ids = col.find_cards(query)[:limit]
        results = []
        for cid in card_ids:
            try:
                card = col.get_card(CardId(cid))
                deck = col.decks.get(card.did)
                results.append(
                    {
                        "card_id": int(card.id),
                        "note_id": int(card.nid),
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
        return results

    def summary_fn(data: list[dict[str, Any]]) -> dict[str, Any]:
        return {
            "query": query,
            "total_matches": len(data),
            "sample_card_ids": [r["card_id"] for r in data[:5]],
        }

    return execute_tool(
        operation="search_cards",
        action=action,
        output_file=output_file,
        summary_fn=summary_fn,
    )


# ============================================================================
# Statistics & Media / Export Utilities
# ============================================================================


@server.tool()
def get_collection_stats(output_file: str | None = None) -> dict[str, Any]:
    """Get collection statistics (total notes, cards, new/due cards, deck breakdown)."""

    def action(col: Collection, _: Any) -> dict[str, Any]:
        decks_breakdown = [
            {
                "id": entry.id,
                "name": entry.name,
                "cards": col.decks.card_count(
                    dids=DeckId(entry.id), include_subdecks=True
                ),
            }
            for entry in col.decks.all_names_and_ids()
        ]
        db = col.db
        if db is None:
            raise RuntimeError("Database connection not available")
        return {
            "total_notes": db.scalar("select count() from notes"),
            "total_cards": db.scalar("select count() from cards"),
            "new_cards": len(col.find_cards("is:new")),
            "due_cards": len(col.find_cards("is:due")),
            "decks": decks_breakdown,
        }

    def summary_fn(data: dict[str, Any]) -> dict[str, Any]:
        return {
            "total_notes": data["total_notes"],
            "total_cards": data["total_cards"],
            "new_cards": data["new_cards"],
            "due_cards": data["due_cards"],
            "deck_count": len(data["decks"]),
        }

    return execute_tool(
        operation="get_collection_stats",
        action=action,
        output_file=output_file,
        summary_fn=summary_fn,
    )


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
                    dids=DeckId(entry.id), include_subdecks=True
                ),
            }
            for entry in col.decks.all_names_and_ids()
        ]
        return json.dumps(decks, indent=2)


@server.resource("anki://stats")
def get_stats_resource() -> str:
    """Resource returning collection overview and due statistics as JSON."""
    with get_collection() as col:
        db = col.db
        if db is None:
            raise RuntimeError("Database connection not available")
        stats = {
            "total_notes": db.scalar("select count() from notes"),
            "total_cards": db.scalar("select count() from cards"),
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
6. Save your card payload to a temporary JSON file before calling `add_notes(input_file=...)`.
"""
