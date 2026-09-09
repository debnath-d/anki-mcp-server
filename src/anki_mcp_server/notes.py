from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from anki.cards import CardId
from anki.collection import AddNoteRequest, Collection
from anki.notes import Note


@dataclass
class IngestedNote:
    """Metadata representing an ingested note and its generated cards."""

    note_id: int
    deck_id: int
    deck_name: str
    notetype_name: str
    tags: list[str]
    fields: dict[str, str]
    cards_generated: int
    card_ids: list[int]
    suspended: bool

    def to_dict(self) -> dict[str, Any]:
        return {
            "note_id": self.note_id,
            "deck_id": self.deck_id,
            "deck_name": self.deck_name,
            "notetype_name": self.notetype_name,
            "tags": self.tags,
            "fields": self.fields,
            "cards_generated": self.cards_generated,
            "card_ids": self.card_ids,
            "suspended": self.suspended,
        }


def _build_note_request(
    col: Collection,
    data: dict[str, Any],
    default_deck: str | None = None,
    default_suspended: bool = False,
) -> tuple[AddNoteRequest, bool, str]:
    """Validate notetype, populate fields and tags, and construct AddNoteRequest."""
    deck_name = data.get("deck_name") or data.get("deck") or default_deck
    if not deck_name:
        raise ValueError("Must specify 'deck_name' for note.")

    deck_id = col.decks.id(deck_name)
    if deck_id is None:
        raise ValueError(f"Could not find or create deck '{deck_name}'.")
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

    return AddNoteRequest(note=note, deck_id=deck_id), suspended, deck_name


def ingest_notes(
    col: Collection,
    payload: dict[str, Any] | list[Any],
    default_deck: str | None = None,
    default_suspended: bool = False,
) -> list[IngestedNote]:
    """Atomically ingest one or more notes into the collection.

    Handles single notes, cloze deletions, and batch arrays.
    Enforces the post-insertion card suspension invariant internally.
    """
    if isinstance(payload, dict):
        notes_list = payload.get("notes") or payload.get("cards")
        if notes_list is None:
            # Single note payload
            notes_list = [payload]
            deck_override = (
                payload.get("deck_name") or payload.get("deck") or default_deck
            )
            suspended_override = bool(payload.get("suspended", default_suspended))
        else:
            if not isinstance(notes_list, list):
                raise TypeError("Payload 'notes' property must be a list.")
            deck_override = (
                payload.get("deck_name") or payload.get("deck") or default_deck
            )
            suspended_override = bool(payload.get("suspended", default_suspended))
    elif isinstance(payload, list):
        notes_list = payload
        deck_override = default_deck
        suspended_override = default_suspended
    else:
        raise TypeError("Note ingestion payload must be a JSON object or array.")

    if not notes_list:
        raise ValueError("No notes provided in ingestion payload.")

    requests: list[AddNoteRequest] = []
    suspension_flags: list[bool] = []
    deck_names: list[str] = []

    for item in notes_list:
        if not isinstance(item, dict):
            raise TypeError(
                f"Each note specification must be an object, got {type(item).__name__}"
            )
        req, should_suspend, d_name = _build_note_request(
            col, item, default_deck=deck_override, default_suspended=suspended_override
        )
        requests.append(req)
        suspension_flags.append(should_suspend)
        deck_names.append(d_name)

    # Ingest into collection
    col.add_notes(requests)

    # Encapsulate post-insertion card suspension invariant
    cards_to_suspend: list[CardId] = []
    for req, should_suspend in zip(requests, suspension_flags):
        if should_suspend:
            cards_to_suspend.extend(req.note.card_ids())

    if cards_to_suspend:
        col.sched.suspend_cards(cards_to_suspend)

    results: list[IngestedNote] = []
    for req, suspended, d_name in zip(requests, suspension_flags, deck_names):
        note: Note = req.note
        cids = list(note.card_ids())
        nt = note.note_type()
        results.append(
            IngestedNote(
                note_id=int(note.id),
                deck_id=int(req.deck_id),
                deck_name=d_name,
                notetype_name=nt["name"] if nt is not None else "",
                tags=list(note.tags),
                fields=dict(note.items()),
                cards_generated=len(cids),
                card_ids=[int(c) for c in cids],
                suspended=suspended,
            )
        )

    return results
