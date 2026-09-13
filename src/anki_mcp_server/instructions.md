# Anki Model Context Protocol (MCP) Server — Agent Reference Manual

The `anki-mcp-server` provides programmatic control over local Anki collections, decks, note types, cards, review queues, tags, media assets, and exports.

---

## 1. System Architecture & Global Protocols

### Universal File-Based I/O Standard
To prevent LLM context saturation and token truncation, this server operates on a strict **Data Plane vs. Control Plane** separation:
* **Control Plane (Telemetry):** All tool calls return compact JSON telemetry (`< 150` tokens) indicating `status`, execution `summary`, and the file path where complete results are stored.
* **Data Plane (Disk Files):** Large inputs (note creation, bulk updates, ID arrays) are passed via `input_file: str`. Unabridged tool outputs are written to `output_file: str`.
* **Cross-Platform Temp Paths:** Tool outputs default to timestamped files under `<temp_dir>/anki_mcp/` (`%TEMP%\anki_mcp\` on Windows, `/tmp/anki_mcp/` on Linux/macOS, or resolved in Python via `Path(tempfile.gettempdir()) / "anki_mcp"`). Never hardcode `/tmp/` on Windows.
* **Reading Tool Outputs:** Inspect `output_file` on disk using targeted line slices or search tools rather than streaming entire files into context.

### Standard Response Envelope
```json
{
  "status": "success",
  "operation": "<tool_name>",
  "summary": {
    "duration_ms": 12.4
  },
  "output_file": "<temp_dir>/anki_mcp/<tool_name>_20260913_153000_a1b2c3.json"
}
```

---

## 2. Master Tool Directory

| Domain | Tool | Input Mode | Output Mode | Summary Description |
| :--- | :--- | :--- | :--- | :--- |
| **Deck Management** | [`list_decks`](#list_decks) | In-Memory | File + Telemetry | List all decks, IDs, and card counts |
| | [`create_deck`](#create_deck) | In-Memory | File + Telemetry | Create a deck or subdeck hierarchy |
| | [`rename_deck`](#rename_deck) | In-Memory | File + Telemetry | Rename a deck and its child subdecks |
| | [`delete_deck`](#delete_deck) | In-Memory | File + Telemetry | Delete a deck and all cards within it |
| | [`change_deck`](#change_deck) | Params / File | File + Telemetry | Relocate cards/notes to another deck |
| **Notetype Schema** | [`list_notetypes`](#list_notetypes) | In-Memory | File + Telemetry | List all notetypes, fields, and templates |
| | [`get_notetype_info`](#get_notetype_info) | In-Memory | File + Telemetry | Retrieve full model schema, CSS, and fields |
| **Note Creation** | [`add_notes`](#add_notes) | `input_file` | File + Telemetry | Ingest Single, Cloze, or Batch notes |
| **Note Mutation** | [`get_note`](#get_note) | In-Memory | File + Telemetry | Inspect full note fields, tags, and cards |
| | [`update_note`](#update_note) | `input_file` | File + Telemetry | Update field values and tags of a note |
| | [`delete_notes`](#delete_notes) | Params / File | File + Telemetry | Delete notes and generated cards |
| **State & Tags** | [`set_card_state`](#set_card_state) | Params / File | File + Telemetry | Suspend or unsuspend cards in bulk |
| | [`update_note_tags`](#update_note_tags) | Params / File | File + Telemetry | Bulk add or remove tags across notes |
| | [`list_tags`](#list_tags) | In-Memory | File + Telemetry | List all unique tags in the collection |
| **Search & Discovery** | [`search_notes`](#search_notes) | In-Memory | File + Telemetry | Search notes via Anki browser query syntax |
| | [`search_cards`](#search_cards) | In-Memory | File + Telemetry | Search cards with review queue metrics |
| **Media, Stats & Export** | [`get_collection_stats`](#get_collection_stats) | In-Memory | File + Telemetry | Get collection overview and due counts |
| | [`store_media_file`](#store_media_file) | File Path | Telemetry | Copy image/audio into Anki media storage |
| | [`export_deck`](#export_deck) | In-Memory | File + Telemetry | Export deck to `.apkg`, `.colpkg`, or JSON |

---

## 3. Comprehensive Tool Specifications

### `list_decks`
* **Purpose:** Inspect all decks and subdecks in the collection with their deck IDs and card counts.
* **Arguments:**
  * `output_file` (`string | null`, optional): Destination file path for the full deck list JSON.
* **Input Payload:** None (pure introspection).
* **Output Payload (`output_file`):** Array of `[{"id": int, "name": str, "card_count": int}, ...]`.
* **Telemetry Summary:** `{"deck_count": int, "total_cards": int, "sample_decks": list[str]}`.
* **Example:**
  ```python
  list_decks()
  ```

---

### `create_deck`
* **Purpose:** Create a new deck or nested subdeck hierarchy (e.g., `Science::Physics::Mechanics`).
* **Arguments:**
  * `deck_name` (`string`, required): Name of deck or subdeck path separated by `::`.
  * `output_file` (`string | null`, optional): Destination file path.
* **Input Payload:** None.
* **Output Payload (`output_file`):** `{"id": int, "name": str}`.
* **Telemetry Summary:** `{"deck_id": int, "deck_name": str}`.
* **Example:**
  ```python
  create_deck(deck_name="Computer Science::Algorithms")
  ```

---

### `rename_deck`
* **Purpose:** Rename an existing deck by ID, cascading changes to all child subdecks.
* **Arguments:**
  * `deck_id` (`integer`, required): ID of the deck to rename.
  * `new_name` (`string`, required): New target name for the deck.
  * `output_file` (`string | null`, optional): Destination file path.
* **Input Payload:** None.
* **Output Payload (`output_file`):** `{"deck_id": int, "old_name": str, "new_name": str}`.
* **Telemetry Summary:** `{"deck_id": int, "old_name": str, "new_name": str}`.
* **Example:**
  ```python
  rename_deck(deck_id=1787001180723, new_name="CS::Data Structures")
  ```

---

### `delete_deck`
* **Purpose:** Delete a deck and all cards/notes contained within it.
* **Arguments:**
  * `deck_id` (`integer | null`, optional): ID of deck to delete (provide `deck_id` or `deck_name`).
  * `deck_name` (`string | null`, optional): Name of deck to delete.
  * `output_file` (`string | null`, optional): Destination file path.
* **Input Payload:** None.
* **Output Payload (`output_file`):** `{"deleted_deck_id": int}`.
* **Telemetry Summary:** `{"deleted_deck_id": int}`.
* **Example:**
  ```python
  delete_deck(deck_name="_UnitTest_Deck")
  ```

---

### `change_deck`
* **Purpose:** Relocate cards or notes into a different deck using query filters, explicit IDs, or an input file.
* **Arguments:**
  * `target_deck_name` (`string | null`, optional): Destination deck name (created if absent).
  * `card_ids` (`list[integer] | null`, optional): Explicit list of card IDs to move.
  * `note_ids` (`list[integer] | null`, optional): Explicit list of note IDs whose cards to move.
  * `query` (`string | null`, optional): Anki search query selecting cards to move.
  * `input_file` (`string | null`, optional): Path to JSON file containing target IDs or query.
  * `output_file` (`string | null`, optional): Destination file path.
* **Input Payload (`input_file`, if used):**
  ```json
  [1787001180723, 1787001180724]
  ```
  or:
  ```json
  {"card_ids": [101, 102], "target_deck_name": "CS::Archived"}
  ```
* **Output Payload (`output_file`):** `{"target_deck_name": str, "target_deck_id": int, "cards_moved": int, "card_ids": list[int]}`.
* **Telemetry Summary:** `{"target_deck_name": str, "target_deck_id": int, "cards_moved": int, "card_ids_count": int}`.
* **Example:**
  ```python
  change_deck(target_deck_name="CS::Algorithms", query='deck:"Default" tag:algo')
  ```

---

### `list_notetypes`
* **Purpose:** Inspect all available note models/types in the collection, including their fields and card templates.
* **Arguments:**
  * `output_file` (`string | null`, optional): Destination file path.
* **Input Payload:** None.
* **Output Payload (`output_file`):** List of `[{"id": int, "name": str, "type": "standard" | "cloze", "fields": list[str], "templates": list[str]}, ...]`.
* **Telemetry Summary:** `{"notetype_count": int, "notetype_names": list[str]}`.
* **Example:**
  ```python
  list_notetypes()
  ```

---

### `get_notetype_info`
* **Purpose:** Retrieve comprehensive schema details for a specific notetype, including field settings, card templates, and CSS styling.
* **Arguments:**
  * `notetype_name` (`string`, required): Name of the notetype (e.g., `"Basic"`, `"Cloze"`).
  * `output_file` (`string | null`, optional): Destination file path.
* **Input Payload:** None.
* **Output Payload (`output_file`):** Detailed schema object containing `id`, `name`, `type`, `fields` (with fonts, order), `templates` (front/back HTML), and `css`.
* **Telemetry Summary:** `{"id": int, "name": str, "type": str, "fields": list[str], "templates": list[str]}`.
* **Example:**
  ```python
  get_notetype_info(notetype_name="Cloze")
  ```

---

### `add_notes`
* **Purpose:** Atomically ingest single notes, cloze deletions, or batch arrays from a JSON file into specified decks.
* **Arguments:**
  * `input_file` (`string`, required): Path to JSON file containing note specification.
  * `deck_name` (`string | null`, optional): Default fallback deck if note specifications omit `deck_name`.
  * `output_file` (`string | null`, optional): Destination file path.
* **Input Payload (`input_file`):**
  * *Option 1: Single Basic Note*
    ```json
    {
      "deck_name": "CS::Algorithms",
      "notetype_name": "Basic",
      "fields": {
        "Front": "What is the average time complexity of QuickSort?",
        "Back": "<p>Average case: $\\mathcal{O}(n \\log n)$</p>"
      },
      "tags": ["algorithms", "sorting"],
      "suspended": false
    }
    ```
  * *Option 2: Cloze Deletion Note*
    ```json
    {
      "deck_name": "CS::Algorithms",
      "is_cloze": true,
      "text": "QuickSort has an average complexity of {{c1::$\\mathcal{O}(n \\log n)$}}.",
      "extra": "<p>Worst case is {{c2::$\\mathcal{O}(n^2)$}}.</p>",
      "tags": ["algorithms", "sorting"]
    }
    ```
  * *Option 3: Batch Note Array*
    ```json
    [
      { "front": "Concept A", "back": "Explanation A", "tags": ["unit-1"] },
      { "front": "Concept B", "back": "Explanation B", "tags": ["unit-1"] }
    ]
    ```
* **Output Payload (`output_file`):** Array of `IngestedNote` records containing `note_id`, `deck_id`, `deck_name`, `notetype_name`, `tags`, `fields`, `cards_generated`, and `card_ids`.
* **Telemetry Summary:** `{"total_created": int, "total_cards": int, "sample_note_ids": list[int], "sample_decks": list[str]}`.
* **Example:**
  ```python
  add_notes(input_file="<temp_dir>/new_cards.json", deck_name="CS::Algorithms")
  ```

---

### `get_note`
* **Purpose:** Retrieve complete field contents, card IDs, deck name, and tags for a single note.
* **Arguments:**
  * `note_id` (`integer`, required): ID of the note to retrieve.
  * `output_file` (`string | null`, optional): Destination file path.
* **Input Payload:** None.
* **Output Payload (`output_file`):** Full note dictionary: `{"note_id": int, "guid": str, "notetype_name": str, "deck_name": str, "tags": list[str], "fields": dict[str, str], "cards": list[dict]}`.
* **Telemetry Summary:** `{"note_id": int, "notetype_name": str, "deck_name": str, "tags": list[str], "cards_count": int}`.
* **Example:**
  ```python
  get_note(note_id=1787001180723)
  ```

---

### `update_note`
* **Purpose:** Update field values and/or tags of an existing note from a JSON file.
* **Arguments:**
  * `note_id` (`integer`, required): ID of note to update.
  * `input_file` (`string`, required): Path to JSON file containing updated fields or tags.
  * `output_file` (`string | null`, optional): Destination file path.
* **Input Payload (`input_file`):**
  ```json
  {
    "fields": {
      "Back": "<p>Updated explanation with math: $$E = mc^2$$</p>"
    },
    "tags": ["physics", "relativity"]
  }
  ```
* **Output Payload (`output_file`):** `{"note_id": int, "tags": list[str], "fields": dict[str, str], "updated_fields": list[str]}`.
* **Telemetry Summary:** `{"note_id": int, "tags": list[str], "updated_fields": list[str]}`.
* **Example:**
  ```python
  update_note(note_id=1787001180723, input_file="<temp_dir>/update_note.json")
  ```

---

### `delete_notes`
* **Purpose:** Permanently remove notes (and all cards generated from them) by IDs or file list.
* **Arguments:**
  * `note_ids` (`list[integer] | null`, optional): Explicit note IDs to delete.
  * `input_file` (`string | null`, optional): Path to JSON file containing note IDs.
  * `output_file` (`string | null`, optional): Destination file path.
* **Input Payload (`input_file`, if used):** `[1787001180723, 1787001180724]`.
* **Output Payload (`output_file`):** `{"deleted_count": int, "deleted_note_ids": list[int]}`.
* **Telemetry Summary:** `{"deleted_count": int, "deleted_note_ids_count": int}`.
* **Example:**
  ```python
  delete_notes(note_ids=[1787001180723, 1787001180724])
  ```

---

### `set_card_state`
* **Purpose:** Bulk suspend or unsuspend cards matching target IDs, note IDs, search queries, or file lists.
* **Arguments:**
  * `state` (`"suspended" | "active"`, default: `"suspended"`): Desired queue state.
  * `card_ids` (`list[integer] | null`, optional): Target card IDs.
  * `note_ids` (`list[integer] | null`, optional): Target note IDs.
  * `query` (`string | null`, optional): Anki search query (e.g. `tag:leech`).
  * `input_file` (`string | null`, optional): Path to JSON file with target IDs or criteria.
  * `output_file` (`string | null`, optional): Destination file path.
* **Input Payload (`input_file`, if used):** `[101, 102]` or `{"query": "tag:leech", "state": "suspended"}`.
* **Output Payload (`output_file`):** `{"state": "suspended" | "active", "cards_affected": int, "card_ids": list[int]}`.
* **Telemetry Summary:** `{"state": str, "cards_affected": int, "card_ids_count": int}`.
* **Example:**
  ```python
  set_card_state(state="suspended", query='deck:"Biology" tag:leech')
  ```

---

### `update_note_tags`
* **Purpose:** Bulk add or remove tags across notes matching IDs, search queries, or file criteria.
* **Arguments:**
  * `action` (`"add" | "remove"`, required): Tag mutation operation.
  * `tags` (`list[string] | null`, optional): Tags to add or remove.
  * `note_ids` (`list[integer] | null`, optional): Target note IDs.
  * `query` (`string | null`, optional): Anki search query to resolve target notes.
  * `input_file` (`string | null`, optional): Path to JSON file with criteria.
  * `output_file` (`string | null`, optional): Destination file path.
* **Input Payload (`input_file`, if used):** `{"tags": ["reviewed"], "query": "deck:Spanish"}`.
* **Output Payload (`output_file`):** `{"action": "add" | "remove", "notes_affected": int, "tags": list[str], "note_ids": list[int]}`.
* **Telemetry Summary:** `{"action": str, "notes_affected": int, "tags": list[str], "note_ids_count": int}`.
* **Example:**
  ```python
  update_note_tags(action="add", tags=["reviewed_2026"], query='deck:"Algorithms"')
  ```

---

### `list_tags`
* **Purpose:** List all unique tags currently existing across the entire Anki collection.
* **Arguments:**
  * `output_file` (`string | null`, optional): Destination file path.
* **Input Payload:** None.
* **Output Payload (`output_file`):** Array of tag strings `["algorithms", "math", "spanish::vocab"]`.
* **Telemetry Summary:** `{"tag_count": int, "sample_tags": list[str]}`.
* **Example:**
  ```python
  list_tags()
  ```

---

### `search_notes`
* **Purpose:** Search notes using Anki browser syntax, writing full matched notes and fields to disk.
* **Arguments:**
  * `query` (`string`, required): Search filter using Anki query syntax.
  * `limit` (`integer`, default: `500`): Maximum number of notes to retrieve.
  * `output_file` (`string | null`, optional): Destination file path.
* **Input Payload:** None.
* **Output Payload (`output_file`):** Array of note records with full fields, tags, and card IDs.
* **Telemetry Summary:** `{"query": str, "total_matches": int, "sample_note_ids": list[int]}`.
* **Example:**
  ```python
  search_notes(query='deck:"CS::Algorithms" tag:sorting')
  ```

---

### `search_cards`
* **Purpose:** Search cards with review queue metrics (interval, due date, reps, lapses, queue status).
* **Arguments:**
  * `query` (`string`, required): Search filter using Anki query syntax.
  * `limit` (`integer`, default: `500`): Maximum number of cards to retrieve.
  * `output_file` (`string | null`, optional): Destination file path.
* **Input Payload:** None.
* **Output Payload (`output_file`):** Array of card records including `card_id`, `note_id`, `deck_id`, `queue_name`, `type_name`, `due`, `interval`, `reps`, `lapses`.
* **Telemetry Summary:** `{"query": str, "total_matches": int, "sample_card_ids": list[int]}`.
* **Example:**
  ```python
  search_cards(query='is:due deck:"Spanish"')
  ```

---

### `get_collection_stats`
* **Purpose:** Fetch high-level statistics across the collection, including card totals, queue distributions, and per-deck counts.
* **Arguments:**
  * `output_file` (`string | null`, optional): Destination file path.
* **Input Payload:** None.
* **Output Payload (`output_file`):** Complete collection metrics dictionary including `total_notes`, `total_cards`, `queues` breakdown, and per-deck stats.
* **Telemetry Summary:** `{"total_notes": int, "total_cards": int, "new_cards": int, "due_cards": int, "deck_count": int}`.
* **Example:**
  ```python
  get_collection_stats()
  ```

---

### `store_media_file`
* **Purpose:** Ingest an image, audio file, or diagram from local disk into Anki's media storage.
* **Arguments:**
  * `source_path` (`string`, required): Path to source file on disk.
  * `target_name` (`string | null`, optional): Target filename in Anki storage (defaults to source filename).
* **Input Payload:** None.
* **Output / Telemetry:** Directly returns embedding snippets:
  ```json
  {
    "status": "success",
    "summary": {
      "filename": "quicksort_partition.svg",
      "size_bytes": 45120,
      "html_embed": "<img src=\"quicksort_partition.svg\">",
      "markdown_embed": "![quicksort_partition.svg](quicksort_partition.svg)"
    }
  }
  ```
* **Example:**
  ```python
  store_media_file(source_path="/home/user/diagrams/quicksort.svg")
  ```

---

### `export_deck`
* **Purpose:** Export a deck to an Anki package (`.apkg`), full collection package (`.colpkg`), or JSON file.
* **Arguments:**
  * `deck_name` (`string`, required): Name of deck to export.
  * `target_path` (`string`, required): Output destination path on disk.
  * `format` (`"apkg" | "colpkg" | "json"`, default: `"apkg"`): Export format.
  * `include_media` (`boolean`, default: `true`): Include referenced media assets in package.
* **Input Payload:** None.
* **Output / Telemetry:**
  ```json
  {
    "status": "success",
    "summary": {
      "deck_name": "CS::Algorithms",
      "format": "apkg",
      "target_path": "/home/user/exports/algorithms.apkg",
      "size_bytes": 1048576
    }
  }
  ```
* **Example:**
  ```python
  export_deck(
      deck_name="CS::Algorithms",
      target_path="<export_dir>/algorithms.apkg",
      format="apkg",
  )
  ```

---

## 4. MCP Resources & Prompts

### Resources
* **`anki://decks`**: JSON list of all active decks with IDs and card counts.
* **`anki://stats`**: JSON collection overview showing total notes, cards, and new/due counts.

### Prompts
* **`flashcard_generator`**: Interactive prompt guiding the creation of atomic flashcards with LaTeX formulas, code fences, and hierarchical tags. Arguments: `topic`, `concept`, `deck_name?`, `difficulty?`.

---

## 5. Anki Search Query Reference

When supplying `query` parameters to `search_notes`, `search_cards`, `change_deck`, `set_card_state`, or `update_note_tags`, use standard Anki query operators:
* `deck:"CS::Algorithms"` — Exact deck match (or `deck:CS::*` for prefix wildcards).
* `tag:algorithms` — Cards with a specific tag (or `tag:algo*` for wildcard matches).
* `is:due` — Cards currently waiting for review.
* `is:new` — Unseen cards in the new queue.
* `is:suspended` — Suspended cards excluded from review.
* `added:1` — Cards created within the last 1 day.
* `prop:reps>10` — Cards reviewed more than 10 times.
* `prop:lapses>3` — Cards failed more than 3 times (leeches).
* `note:Basic` or `note:Cloze` — Cards generated from a specific notetype.

---

## 6. Flashcard Authoring & Formatting Standards

1. **Principle of Atomicity:** Each card must test exactly one core fact, definition, or concept. Avoid multi-part lists on a single card.
2. **Cloze Formatting:** Use `{{c1::answer}}` or `{{c1::answer::hint}}`. For multiple cloze deletions on one card, use `{{c1::first}}` and `{{c2::second}}`.
3. **LaTeX Math Support:**
   * Inline: `$x = \frac{-b \pm \sqrt{b^2 - 4ac}}{2a}$`
   * Block / Display: `$$\int_{-\infty}^{\infty} e^{-x^2} dx = \sqrt{\pi}$$`
4. **Code Blocks:** Use semantic HTML `<pre><code>...</code></pre>` tags.
5. **Hierarchical Tags:** Group cards using nested tags separated by `::` (e.g. `cs::algorithms::sorting`).
