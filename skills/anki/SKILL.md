---
name: anki
description: >-
  Anki flashcard creation, bulk programmatic ingestion, card refactoring, and collection management via anki-mcp-server.
  Use when the user asks to create flashcards from text or code, batch ingest study materials (problem sets, book excerpts),
  triage difficult cards or leeches, or manage Anki decks, tags, and notetypes.
---

# Anki Agent Skill

This skill guides agents in creating, ingesting, refactoring, and maintaining Anki flashcards using the `anki-mcp-server`. It implements an **evolutionary card lifecycle** (cards start as reading material/seed notes and are progressively refined) and follows a **strict file-based I/O contract** to keep token usage low.

---

## 1. Operating Modes

Agents interact with Anki across two primary modes:

1. **Fast Programmatic Ingestion (Seeding):**
   * High-throughput ingestion of curated problem sets (e.g. NeetCode, LeetCode), book excerpts, API documentation, or lecture notes.
   * **Token Conservation Priority:** Do NOT waste tokens deeply analyzing or explaining the material upfront. Use quick Python scripts or JSON batching to assemble the payload directly into the OS temporary directory (`Path(tempfile.gettempdir()) / "anki_mcp"`, e.g., `%TEMP%\anki_mcp\` on Windows or `/tmp/anki_mcp/` on Linux/macOS) and call `add_notes(input_file=...)`.
2. **Progressive Refactoring & Triage (Evolution):**
   * Diagnosing failing cards or leeches (`prop:lapses>4`).
   * Splitting unwieldy cards into atomic units, adding cloze deletions, or resolving memory interference between confusable concepts.
   * Updating cards in place via `update_note`.

---

## 2. Universal File-Based I/O Protocol

To avoid saturating the context window, `anki-mcp-server` enforces separation between the **Control Plane** and **Data Plane**:

* **Writing to Anki:** Always write batch notes or update payloads to a JSON file on disk (resolve the path via `Path(tempfile.gettempdir()) / "anki_mcp" / "payload_<timestamp>.json"`), then pass `input_file=str(payload_path)` to the tool.
* **Reading from Anki:** Search, note, and deck inspection tools return small telemetry dictionaries (`< 150` tokens) containing an `output_file` path (e.g., `<temp_dir>/anki_mcp/search_notes_....json`). Inspect the output file on disk using targeted line slices or search tools rather than dumping full collection data into conversation context.
* **Cross-Platform Compatibility:** Never hardcode `/tmp/` if running in an unknown environment or on Windows. Always use `tempfile.gettempdir()`, `%TEMP%`, or environment variables.

---

## 3. Core References

Consult these detailed references on demand:

* **[Knowledge Formulation Guide](references/knowledge-formulation.md):** The pragmatic agent edition of spaced-repetition rules — card evolution lifecycle, formatting (LaTeX, code fences), context cues, and pragmatic handling of sets and enumerations.
* **[Workflows & Playbooks](references/workflows.md):** Step-by-step execution guides for bulk script ingestion, interactive card authoring, leech triage, and deck maintenance.
* **[Query Cheatsheet](references/query-cheatsheet.md):** Reference for Anki browser search filters (`is:due`, `tag:`, `deck:`, `prop:lapses`, `added:N`).

---

## 4. Quick Execution Steps

### Step 1: Introspect Schema & Target Deck
Before creating notes, check the available decks and note types:
```python
# Check existing decks
list_decks()

# Check available note types and field names (e.g. Basic, Cloze)
list_notetypes()
```

### Step 2: Prepare JSON Payload on Disk
Write your card specifications to a JSON file in the temporary directory. In Python, this is OS-agnostic:
```python
import json
import tempfile
from pathlib import Path

out_dir = Path(tempfile.gettempdir()) / "anki_mcp"
out_dir.mkdir(parents=True, exist_ok=True)
payload_file = out_dir / "new_cards.json"

payload_file.write_text(json.dumps([...], indent=2), encoding="utf-8")
```
See [examples/basic_cards.json](examples/basic_cards.json) or [examples/cloze_cards.json](examples/cloze_cards.json).

### Step 3: Ingest via `add_notes`
```python
add_notes(input_file=str(payload_file), deck_name="Target::Deck")
```

### Step 4: Verify Telemetry
Inspect the returned telemetry summary (`total_created`, `total_cards`, `output_file`). If verification of created notes is required, read targeted entries from `output_file`.

