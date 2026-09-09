from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from anki.cards import CardId
from anki.collection import Collection
from anki.errors import AnkiError, NotFoundError
from anki.notes import NoteId

from anki_mcp_server.io_utils import read_json_file


@dataclass
class TargetSpec:
    """Polymorphic specification for targeting flashcard entities."""

    card_ids: list[int] | None = None
    note_ids: list[int] | None = None
    query: str | None = None
    input_file: str | None = None
    _cached_payload: Any = field(default=None, repr=False, init=False)

    def get_file_payload(self) -> Any:
        """Retrieve and cache the parsed payload from input_file if present."""
        if self._cached_payload is None and self.input_file:
            self._cached_payload = read_json_file(self.input_file)
        return self._cached_payload

    def resolve_card_ids(self, col: Collection) -> list[CardId]:
        """Extract and validate a deduplicated list of CardIds."""
        target_cids: set[int] = set()

        if self.input_file:
            file_data = self.get_file_payload()
            if isinstance(file_data, dict):
                self.card_ids = self.card_ids or file_data.get("card_ids")
                self.note_ids = self.note_ids or file_data.get("note_ids")
                self.query = self.query or file_data.get("query")
            elif isinstance(file_data, list):
                self.card_ids = self.card_ids or file_data

        if self.card_ids:
            target_cids.update(self.card_ids)

        if self.note_ids:
            for nid in self.note_ids:
                try:
                    note = col.get_note(NoteId(nid))
                    target_cids.update(note.card_ids())
                except (AnkiError, NotFoundError, KeyError):
                    continue

        if self.query:
            target_cids.update(col.find_cards(self.query))

        if not target_cids:
            raise ValueError("No cards specified or found matching the criteria.")

        return [CardId(cid) for cid in sorted(target_cids)]

    def resolve_note_ids(self, col: Collection | None = None) -> list[NoteId]:
        """Extract and validate a deduplicated list of NoteIds."""
        target_nids: set[int] = set()

        if self.input_file:
            file_data = self.get_file_payload()
            if isinstance(file_data, list):
                self.note_ids = self.note_ids or file_data
            elif isinstance(file_data, dict):
                self.note_ids = self.note_ids or file_data.get("note_ids")
                self.card_ids = self.card_ids or file_data.get("card_ids")
                self.query = self.query or file_data.get("query")

        if self.note_ids:
            target_nids.update(self.note_ids)

        if col is not None:
            if self.card_ids:
                for cid in self.card_ids:
                    try:
                        card = col.get_card(CardId(cid))
                        target_nids.add(int(card.nid))
                    except (AnkiError, NotFoundError, KeyError):
                        continue

            if self.query:
                target_nids.update(col.find_notes(self.query))

        if not target_nids:
            raise ValueError("No notes specified or found matching the criteria.")

        return [NoteId(nid) for nid in sorted(target_nids)]
