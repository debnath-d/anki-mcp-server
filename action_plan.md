# Action Plan: Anki MCP Server Feature Extension

---

## 1. Scope of Tools to Implement

| # | Feature | Tool Name | Description / Use Case |
| :--- | :--- | :--- | :--- |
| **1** | **Move Notes / Decks** | `change_deck` | Reorganizing cards across topic subdecks (e.g. moving cards from `Uncategorized` to `Science::Physics::Mechanics`) by `card_ids`, `note_ids`, or search `query`. |
| **2** | **Media & Image Storage** | `store_media_file` | Inserting anatomical diagrams, state transition graphs, circuit schematics, and plots into Anki's media storage from local `source_path`. |
| **3** | **Card State Control** | `suspend_cards` / `unsuspend_cards` | Generating full chapters of cards in a suspended state, and only unsuspending the specific topics you are actively studying that week. |
| **4** | **Deck Renaming & Reparenting** | `rename_deck` | Renames existing decks or reorganizes the subdeck hierarchy in place by `deck_id` and `new_name`. |
| **5** | **Direct Suspended Note Creation** | `add_note` / `add_cloze_note` / `add_notes_batch` | Added optional `suspended: bool = False` flag to create notes with all generated cards immediately suspended. |

---

## 2. Tool Signatures & Specifications

1. **`change_deck(target_deck_name: str, card_ids: list[int] | None = None, note_ids: list[int] | None = None, query: str | None = None) -> dict`**
   - Resolves `target_deck_name` to `deck_id` (creates deck automatically if it doesn't exist).
   - Collects card IDs from `card_ids`, notes (`note_ids`), or search string (`query`).
   - Calls `col.set_deck(card_ids, deck_id)`.
   - Returns number of cards moved and list of affected card IDs.

2. **`store_media_file(filename: str | None = None, file_path: str | None = None, data_base64: str | None = None) -> dict`**
   - Validates that either `file_path` exists on disk or `data_base64` is provided.
   - Writes media using `col.media.write_data(...)` or `col.media.add_file(...)`.
   - Returns stored filename, `<img src="...">` HTML embed tag, and `![...]` markdown tag.

3. **`suspend_cards(card_ids: list[int] | None = None, note_ids: list[int] | None = None, query: str | None = None) -> dict`**
   - Collects card IDs from `card_ids`, `note_ids`, or `query`.
   - Calls `col.sched.suspend_cards(card_ids)`.
   - Returns count and IDs of suspended cards.

4. **`unsuspend_cards(card_ids: list[int] | None = None, note_ids: list[int] | None = None, query: str | None = None) -> dict`**
   - Collects card IDs from `card_ids`, `note_ids`, or `query`.
   - Calls `col.sched.unsuspend_cards(card_ids)`.
   - Returns count and IDs of unsuspended cards.

5. **`rename_deck(deck_id: int, new_name: str) -> dict`**
   - Calls `col.decks.rename(deck_id, new_name)`.
   - Automatically renames child subdecks matching the prefix.

6. **Note Creation Tool Updates (`add_note`, `add_cloze_note`, `add_notes_batch`)**
   - Add `suspended: bool = False` argument.
   - When `True`, automatically suspends all generated cards upon creation.

---

## 3. Automated Testing & Verification
1. **Unit Tests in `tests/test_server.py`**:
   - Test moving cards between subdecks with `change_deck` via `card_ids`, `note_ids`, and `query`.
   - Test storing media with `store_media_file` via `file_path` and `data_base64`.
   - Test suspending and unsuspending cards with `suspend_cards` / `unsuspend_cards` and verifying queue status (`queue == -1`).
   - Test creating suspended cards directly via `add_note(..., suspended=True)`.
   - Test renaming decks and checking hierarchical subdeck renaming with `rename_deck`.
   - Test MCP server tool listing and call execution.
