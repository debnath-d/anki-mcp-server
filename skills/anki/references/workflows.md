# Anki Execution Workflows & Playbooks

This guide provides step-by-step playbooks for agents interacting with `anki-mcp-server`.

---

## Playbook 1: Token-Efficient Bulk Ingestion

Use this playbook when ingesting large collections (e.g. 50–150+ coding problems, lecture notes, textbook chapters, or API reference tables).

### Objective
Ingest dozens or hundreds of cards with minimal LLM context consumption. Never serialize entire problem sets into conversation prompt tokens.

### Step-by-Step Procedure

1. **Verify Target Deck & Schema:**
   ```python
   list_decks()
   list_notetypes()
   ```
   Ensure the destination deck exists (or call `create_deck(deck_name="...")`).
2. **Assemble Payload via Script (Cross-Platform):**
   Write a small helper script (or use Python) to parse the source material (CSV, Markdown, JSON, repo files) and output directly to the OS temporary directory (`Path(tempfile.gettempdir()) / "anki_mcp"`):
   ```python
   # Cross-platform pattern: writes directly to OS temp directory
   import json
   import tempfile
   from pathlib import Path

   temp_dir = Path(tempfile.gettempdir()) / "anki_mcp"
   temp_dir.mkdir(parents=True, exist_ok=True)
   payload_path = temp_dir / "batch_ingest.json"

   cards = [
       {
           "deck_name": "CS::NeetCode 150",
           "notetype_name": "Basic",
           "fields": {
               "Front": f"[NeetCode: {item['category']}] {item['title']}\n<p>{item['prompt']}</p>",
               "Back": f"<pre><code>{item['solution']}</code></pre><p>Time: ${item['time_complexity']}$, Space: ${item['space_complexity']}$</p>",
           },
           "tags": ["neetcode", item["category"].lower().replace(" ", "-")],
       }
       for item in source_data
   ]

   payload_path.write_text(
       json.dumps(cards, indent=2, ensure_ascii=False), encoding="utf-8"
   )
   ```
3. **Execute Ingestion:**
   ```python
   add_notes(input_file=str(payload_path))
   ```
4. **Inspect Telemetry:**
   Review the compact returned response:
   ```json
   {
     "status": "success",
     "summary": {
       "total_created": 150,
       "total_cards": 150,
       "sample_note_ids": [1787001180723, 1787001180724]
     },
     "output_file": "<temp_dir>/anki_mcp/add_notes_...json"
   }
   ```

---

## Playbook 2: Interactive Card Authoring

Use this playbook when the user asks to create flashcards from a specific snippet, concept, or conversation context.

### Step-by-Step Procedure

1. **Introspect & Deduplicate:**
   * Verify the target deck with `list_decks()`.
   * Search for existing cards to avoid duplicates:
     ```python
     search_notes(query='deck:"Algorithms" "QuickSort"')
     ```
2. **Draft Cards Adhering to Formulation Guidelines:**
   * See [Knowledge Formulation Guide](knowledge-formulation.md).
   * Apply context cues (`[Topic]`), atomic questions, or cloze deletions.
   * Format LaTeX with `$...$` and code with `<pre><code>...</code></pre>`.
3. **Write Payload to Disk:**
   Save to the OS temporary directory (e.g. `Path(tempfile.gettempdir()) / "anki_mcp" / "new_notes.json"`).
4. **Call `add_notes`:**
   ```python
   add_notes(input_file=str(payload_path), deck_name="CS::Algorithms")
   ```
5. **Confirm with the User:**
   Report the number of cards created and the target deck.

---

## Playbook 3: Leech Triage & Progressive Refactoring

Use this playbook when the user wants to audit failed cards or improve cards with poor retention.

### Step-by-Step Procedure

1. **Locate Leeches & High-Lapse Cards:**
   ```python
   search_cards(query="prop:lapses>=4 is:due")
   ```
   * Anki marks cards as leeches when they repeatedly fail review.
2. **Inspect Problematic Notes:**
   Examine the `output_file` from `search_cards` to find note IDs, then retrieve the full note:
   ```python
   get_note(note_id=1787001180723)
   ```
3. **Diagnose Failure Modes:**
   * **Set Anti-pattern:** Does the card ask to recite a large list of 5+ things?
   * **Ambiguous Prompt:** Does the question lack a context cue?
   * **Interference:** Is it easily confused with another concept in the same deck?
   * **Oversized Reading Block:** Is it a raw reading note that was never broken down?
4. **Remediate:**
   * **In-place Update:** If the card simply needs clearer wording or LaTeX fixes, write the patch JSON to the OS temporary directory (`patch_path = Path(tempfile.gettempdir()) / "anki_mcp" / "patch_note.json"`) and run:
     ```python
     update_note(note_id=1787001180723, input_file=str(patch_path))
     ```
   * **Decomposition / Splitting:** If the card is too broad, delete the original note:
     ```python
     delete_notes(note_ids=[1787001180723])
     ```
     Then ingest 2–3 new atomic cards via `add_notes`.

---

## Playbook 4: Collection Maintenance & Bulk Operations

### Bulk Deck Reorganization
Move all cards matching a query or ID list to a new or archived deck:
```python
change_deck(target_deck_name="CS::Archived", query='deck:"CS::Algorithms" tag:obsolete')
```

### Bulk Tagging
Add or remove tags across matching cards:
```python
update_note_tags(action="add", tags=["reviewed_2026"], query='deck:"Calculus"')
```

### Card Suspension
Temporarily suspend difficult cards or cards not currently in scope:
```python
set_card_state(state="suspended", query='deck:"Biology" tag:postponed')
```

### Collection Export
Create a backup archive (`.apkg`):
```python
export_deck(
    deck_name="CS::Algorithms",
    target_path=str(Path.home() / "backups" / "algorithms.apkg"),
    format="apkg",
)
```

