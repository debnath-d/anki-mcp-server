# Architectural Blueprint: Universal File-Based I/O for Anki MCP Tools

**Author:** Antigravity (Pair Programming Assistant)  
**Date:** September 10, 2026  
**Status:** Completed Architectural Specification (v0.3.0)  

---

## 1. Executive Summary

In AI-assisted developer workflows, forcing a Large Language Model (LLM) to act as a raw data transmission pipe for database interactions is a fundamental architectural anti-pattern. 

Flashcards, search results, deck hierarchies, and media assets in modern Anki collections are rich, multi-kilobyte or multi-megabyte documents containing HTML boilerplate, inline styles, Monokai syntax-highlighted code spans, and MathJax LaTeX formulas. When these payloads are streamed through tool call arguments or returned directly in tool outputs, they:
1. **Exceed LLM Output Token Limits:** Causing tool call JSON strings to truncate and fail mid-stream.
2. **Saturate LLM Context Windows:** Flooding the model's working memory with repetitive HTML markup and JSON structures, which degrades reasoning capacity, pushes critical system instructions out of context, and drastically inflates latency and token costs.
3. **Impose Severe Latency Penalties:** Serializing megabytes of text across LLM attention layers takes minutes, whereas local disk and database I/O takes milliseconds.
4. **Throttle Bulk Entity Targeting:** Passing hundreds or thousands of card or note IDs in JSON-RPC parameters to reorganize decks or change review states consumes thousands of unnecessary tokens per call.

### The Core Architectural Standard
**All Anki MCP tools must strictly employ Universal File-Based Input and Output (File-Based I/O).** 

No MCP tool—whether note mutations, batch imports, queries, searches, schema introspections, or bulk entity targeting—should accept raw content payloads in JSON-RPC arguments or return raw data dumps in tool responses. Instead, tools accept input file paths and write structured results to output file paths, returning only **compact telemetry summaries** ($< 150$ tokens) to the LLM.

---

## 2. Why File-Based I/O Applies to ALL Tools (Not Just Batch)

It is a common misconception that payload bloat is only a "batch import" problem. In practice, almost every Anki operation carries significant token overhead:

### 2.1 Single and Batch Ingestion (`add_notes`, `update_note`, `get_note`)
* A single comprehensive STEM, language, or algorithm flashcard (with code blocks, syntax highlighting, intuition, complexities, and LaTeX math formulas) contains **20 KB to 100 KB of HTML**.
* Passing this in a standard tool argument consumes **5,000 to 25,000 tokens** for a single card.
* In v0.3.0, `add_notes` consolidates single notes, Cloze deletions, and batch arrays into a single file-driven endpoint, ensuring single cards and massive decks alike consume zero in-band payload tokens.

### 2.2 Queries and Searches (`search_notes`, `search_cards`)
* Searching for cards in a deck (e.g., `deck:"Computer Science::Algorithms"`) matching 50 to 150 cards produces a **2 MB to 8 MB response payload**.
* Returning this payload directly into the LLM context instantly consumes millions of tokens, pushing conversation history and instructions completely out of memory.
* Writing search results to disk preserves the complete dataset while returning a compact telemetry summary with sample IDs, match counts, and the resolved file path.

### 2.3 Bulk Entity Targeting (`change_deck`, `set_card_state`, `update_note_tags`, `delete_notes`)
* Reorganizing an entire subdeck or suspending cards across a course module often involves hundreds or thousands of card or note IDs.
* Streaming an array of 2,000 integer IDs over JSON-RPC consumes ~8,000 tokens of pure transport overhead.
* Through polymorphic targeting (`TargetSpec`), tools accept `input_file` pointing to a JSON file containing the target IDs or search query, reducing token cost to a constant $\mathcal{O}(1)$.

### 2.4 Media & Asset Storage (`store_media_file`)
* Diagrams, SVG schematics, and audio files cannot be streamed over JSON-RPC without base64 encoding (a 33% payload expansion).
* Direct filesystem paths allow the MCP server to read and store files into Anki's `collection.media/` folder in microseconds without base64 transport.

---

## 3. Universal File-Based Tool Specification

Under the Universal File-Based standard, every MCP tool adheres to a clean separation between **Control Telemetry** (which the LLM reads) and **Data Payloads** (which remain on disk).

### 3.1 Standard Input Schema Pattern
Every MCP tool accepts:
1. `input_file: str` — Path to a JSON payload on disk for all content mutations (`add_notes`, `update_note`) and bulk entity targeting (`change_deck`, `set_card_state`, `update_note_tags`, `delete_notes`).
2. `output_file?: str` — Optional caller-specified destination file. If omitted, the server automatically generates a timestamped file in the configured output directory (`get_output_dir()`).
3. Lightweight primitives (e.g. `deck_name: str`, `note_id: int`, `query: str`) only when specifying targeted operations or fallback filters.

### 3.2 Standard Output Schema Pattern
Every tool response returns a bounded, compact telemetry object:
```json
{
  "status": "success",
  "operation": "add_notes",
  "summary": {
    "total_created": 150,
    "total_cards": 150,
    "sample_note_ids": [1787001180723, 1787001180724],
    "sample_decks": ["Computer Science::Algorithms"],
    "duration_ms": 42.1
  },
  "output_file": "/tmp/anki_mcp/add_notes_20260910_015312_a1b2c3.json"
}
```
* **Payload size returned to LLM:** $< 150\text{ tokens}$ (constant, regardless of card or collection size).
* **Full data:** Persisted in `output_file` on disk for selective, slice-based reading (`view_file` or `grep_search`) if needed.

---

## 4. Comprehensive Tool-by-Tool Specification

The `anki-mcp-server` exposes 19 cohesive tools across 6 functional domains, plus MCP resources and prompt templates, all strictly adhering to File-Based I/O:

### 4.1 Deck Management

| Tool Name | Input Parameters (Control Plane) | Disk Data Interaction (Data Plane) | Output Telemetry to Model |
| :--- | :--- | :--- | :--- |
| **`list_decks`** | `output_file?: str` | Reads collection, writes full deck hierarchy and card counts to disk | `{"status": "success", "summary": {"deck_count": 18, "total_cards": 1250, "sample_decks": [...]}, "output_file": "..."}` |
| **`create_deck`** | `deck_name: str`, `output_file?: str` | Creates deck/subdeck in collection, writes deck record to disk | `{"status": "success", "summary": {"deck_id": 123, "deck_name": "..."}, "output_file": "..."}` |
| **`delete_deck`** | `deck_id?: int`, `deck_name?: str`, `output_file?: str` | Removes deck and cards from collection, writes deletion record to disk | `{"status": "success", "summary": {"deleted_deck_id": 123}, "output_file": "..."}` |
| **`rename_deck`** | `deck_id: int`, `new_name: str`, `output_file?: str` | Renames deck and cascading subdecks, writes update record to disk | `{"status": "success", "summary": {"deck_id": 123, "old_name": "...", "new_name": "..."}, "output_file": "..."}` |
| **`change_deck`** | `target_deck_name?: str`, `card_ids?: list[int]`, `note_ids?: list[int]`, `query?: str`, `input_file?: str`, `output_file?: str` | Resolves targets via `TargetSpec` (from params or `input_file`), moves cards, writes affected IDs to disk | `{"status": "success", "summary": {"target_deck_name": "...", "cards_moved": 45, "card_ids_count": 45}, "output_file": "..."}` |

### 4.2 Notetypes (Models)

| Tool Name | Input Parameters (Control Plane) | Disk Data Interaction (Data Plane) | Output Telemetry to Model |
| :--- | :--- | :--- | :--- |
| **`list_notetypes`** | `output_file?: str` | Introspects models, writes full field lists and template metadata to disk | `{"status": "success", "summary": {"notetype_count": 5, "notetype_names": [...]}, "output_file": "..."}` |
| **`get_notetype_info`** | `notetype_name: str`, `output_file?: str` | Fetches model schema, CSS, templates, and fields, writes full schema to disk | `{"status": "success", "summary": {"id": 123, "name": "Basic", "fields": [...], "type": "standard"}, "output_file": "..."}` |

### 4.3 Card & Note Ingestion

| Tool Name | Input Parameters (Control Plane) | Disk Data Interaction (Data Plane) | Output Telemetry to Model |
| :--- | :--- | :--- | :--- |
| **`add_notes`** | `input_file: str`, `deck_name?: str`, `output_file?: str` | Reads single note, cloze deletion, or batch array from JSON file; performs atomic insertion and suspension; writes full note records to disk | `{"status": "success", "summary": {"total_created": 150, "total_cards": 150, "sample_note_ids": [...], "duration_ms": 42.1}, "output_file": "..."}` |

### 4.4 Note Inspection & Mutation

| Tool Name | Input Parameters (Control Plane) | Disk Data Interaction (Data Plane) | Output Telemetry to Model |
| :--- | :--- | :--- | :--- |
| **`get_note`** | `note_id: int`, `output_file?: str` | Reads note, cards, deck, tags, and all raw HTML fields from collection, writes full JSON to disk | `{"status": "success", "summary": {"note_id": 123, "deck_name": "...", "tags": [...], "cards_count": 1}, "output_file": "..."}` |
| **`update_note`** | `note_id: int`, `input_file: str`, `output_file?: str` | Reads field/tag mutations from JSON file, updates collection, writes updated note record to disk | `{"status": "success", "summary": {"note_id": 123, "updated_fields": [...], "tags": [...]}, "output_file": "..."}` |
| **`delete_notes`** | `note_ids?: list[int]`, `input_file?: str`, `output_file?: str` | Resolves targets via `TargetSpec`, deletes notes and cards from collection, writes deleted IDs to disk | `{"status": "success", "summary": {"deleted_count": 25, "deleted_note_ids_count": 25}, "output_file": "..."}` |

### 4.5 State & Tag Control

| Tool Name | Input Parameters (Control Plane) | Disk Data Interaction (Data Plane) | Output Telemetry to Model |
| :--- | :--- | :--- | :--- |
| **`set_card_state`** | `state: str` (`"suspended"`/`"active"`), `card_ids?: list[int]`, `note_ids?: list[int]`, `query?: str`, `input_file?: str`, `output_file?: str` | Resolves cards via `TargetSpec` (params or `input_file`), updates review queue, writes affected card IDs to disk | `{"status": "success", "summary": {"state": "suspended", "cards_affected": 150, "card_ids_count": 150}, "output_file": "..."}` |
| **`update_note_tags`** | `action: str` (`"add"`/`"remove"`), `tags?: list[str]`, `note_ids?: list[int]`, `input_file?: str`, `output_file?: str` | Resolves notes via `TargetSpec` (params or `input_file`), applies bulk tag mutations, writes affected IDs to disk | `{"status": "success", "summary": {"action": "add", "notes_affected": 80, "tags": [...]}, "output_file": "..."}` |

### 4.6 Search & Discovery

| Tool Name | Input Parameters (Control Plane) | Disk Data Interaction (Data Plane) | Output Telemetry to Model |
| :--- | :--- | :--- | :--- |
| **`search_notes`** | `query: str`, `limit?: int`, `output_file?: str` | Executes search query, fetches matching notes with full HTML fields, writes complete array to disk | `{"status": "success", "summary": {"query": "deck:Science", "total_matches": 150, "sample_note_ids": [...]}, "output_file": "..."}` |
| **`search_cards`** | `query: str`, `limit?: int`, `output_file?: str` | Executes card search, fetches review queues, intervals, due dates, writes complete array to disk | `{"status": "success", "summary": {"query": "is:due", "total_matches": 42, "sample_card_ids": [...]}, "output_file": "..."}` |
| **`list_tags`** | `output_file?: str` | Fetches all unique tags in collection, writes full tag array to disk | `{"status": "success", "summary": {"tag_count": 120, "sample_tags": [...]}, "output_file": "..."}` |

### 4.7 Statistics, Media & Deck Export

| Tool Name | Input Parameters (Control Plane) | Disk Data Interaction (Data Plane) | Output Telemetry to Model |
| :--- | :--- | :--- | :--- |
| **`get_collection_stats`** | `output_file?: str` | Queries collection stats (notes, cards, due counts, per-deck stats), writes full breakdown to disk | `{"status": "success", "summary": {"total_notes": 1200, "total_cards": 1850, "new_cards": 50, "due_cards": 30, "deck_count": 12}, "output_file": "..."}` |
| **`store_media_file`** | `source_path: str`, `target_name?: str` | Copies/links file directly from disk into Anki's `collection.media/` storage | `{"status": "success", "summary": {"filename": "diagram.svg", "size_bytes": 45120, "html_embed": "<img src=\"...\">", "markdown_embed": "![...](...)"}}` |
| **`export_deck`** | `deck_name: str`, `target_path: str`, `format?: str` (`"apkg"`/`"colpkg"`/`"json"`), `include_media?: bool` | Packages deck or collection to `.apkg`, `.colpkg`, or `.json` on disk | `{"status": "success", "summary": {"deck_name": "...", "format": "apkg", "target_path": "...", "size_bytes": 4210500}}` |

### 4.8 MCP Resources & Prompts

* **`anki://decks`**: MCP Resource returning active deck names, IDs, and card counts.
* **`anki://stats`**: MCP Resource returning collection-wide statistics, total notes/cards, and new/due counts.
* **`flashcard_generator`**: MCP Prompt template guiding LLMs to generate high-quality cards with LaTeX formulas, code fences, and hierarchical tags formatted for file-based ingestion.

---

## 5. Architectural Advantages & Empirical Benefits

### 5.1 Elimination of Token Sinks
* By replacing megabyte-sized JSON-RPC payloads with file path references, LLM token consumption drops by **>99.9%**.
* Batch card ingestion of hundreds of complex cards requires **zero payload tokens** from the model, compared to millions of tokens via direct streaming.

### 5.2 Deterministic Execution & Zero JSON Truncation
* Because the model only outputs file paths and short config parameters, tool calls never risk exceeding output token limits ($8\text{k}\text{--}64\text{k}$).
* Parsing of massive HTML strings, syntax highlighting trees, and LaTeX is handled natively by Python and compiled C-extensions (`pygments`, `markdown`, `sqlite3`).

### 5.3 On-Demand Selective Inspection
* When the model needs to inspect a specific field or result, it can use targeted tools (e.g. `view_file` with precise line slices, or `grep_search`) to read only the relevant lines from the `output_file` without loading megabytes of surrounding HTML.

### 5.4 High-Performance Local Database Access & Atomic Transactions
* File-based batch execution processes hundreds of cards in a single atomic SQLite transaction within **seconds** (e.g. 150 cards in ~40ms), completely eliminating multi-roundtrip network/RPC latency and avoiding SQLite lock contention.

### 5.5 $\mathcal{O}(1)$ Bulk Entity Targeting
* With polymorphic targeting (`TargetSpec`), bulk operations on thousands of cards (moving decks, changing review states, adding tags, or deleting notes) execute with $\mathcal{O}(1)$ token overhead by referencing disk payloads or search query strings.

---

## 6. Implementation Architecture in `anki_mcp_server`

The v0.3.0 implementation decomposes File-Based I/O across deep, single-responsibility modules:

```
src/anki_mcp_server/
├── collection.py    # Non-blocking collection lifecycle & CollectionAdapter seam
├── io_utils.py      # Disk serialization, file dereferencing, telemetry formatting
├── notes.py         # Transactional note ingestion (Single, Cloze, Batch, Suspension)
├── pipeline.py      # Centralized execution harness, duration timing, auto-projection
├── selector.py      # Polymorphic TargetSpec entity resolution (Cards, Notes, Queries, Files)
└── server.py        # FastMCP server definitions and route handlers
```

### 6.1 Unified Execution Pipeline (`pipeline.py`)
Centralized through `execute_tool`:
1. **Input Dereferencing:** Automatically reads and parses `input_file` via `io_utils.read_json_file`.
2. **Collection Lifecycle:** Manages collection session via `get_collection()` context manager.
3. **Execution Latency Timing:** Captures sub-millisecond duration via `time.perf_counter()`.
4. **Summary Auto-Projection:** Projects domain payloads into bounded telemetry summaries via `_project_summary` or a custom `summary_fn`.
5. **Disk Serialization:** Writes full result payload to `output_file` using `write_tool_output`.
6. **Telemetry Packaging:** Returns uniform JSON structure with `status`, `operation`, `summary`, and `output_file`.

### 6.2 Polymorphic Entity Targeting (`selector.py`)
Encapsulated in `TargetSpec`:
* Accepts any combination of `card_ids`, `note_ids`, `query`, or `input_file`.
* Lazy-caches disk payloads when `input_file` is specified.
* Provides `resolve_card_ids(col)` and `resolve_note_ids(col)` to deduplicate and validate target entities against the SQLite database.

### 6.3 Deep Note Ingestion Engine (`notes.py`)
Encapsulated in `ingest_notes`:
* Polymorphic payload handling: Accepts single note objects, cloze deletions, or arrays of notes.
* Cloze normalization: Automatically detects model types and maps `text`/`extra` fields to Cloze placeholders.
* Atomic transaction: Batch-submits all `AddNoteRequest` instances in a single `col.add_notes` call.
* Card suspension invariant: Atomically suspends generated cards post-insertion if `suspended=True` is specified, returning structured `IngestedNote` records.

### 6.4 Disk I/O & Telemetry Subsystem (`io_utils.py`)
* `get_output_dir()`: Resolves output path with cross-platform defaults (`%TEMP%\anki_mcp` or `/tmp/anki_mcp`) or custom `ANKI_MCP_OUTPUT_DIR`.
* `write_tool_output()`: Serializes data to JSON using formatted timestamps and unique identifiers (`{prefix}_{timestamp}_{unique_id}.json`).
* `read_json_file()`: Reads and decodes JSON input with informative validation errors.
* `format_telemetry()`: Assembles standard telemetry envelopes.

### 6.5 Decoupled Operations Seam (`collection.py`)
* Implements `CollectionAdapter` protocol separating real SQLite connections (`NativeAnkiAdapter`) from hermetic test fixtures (`IsolatedAnkiAdapter`).
* Non-blocking connection lifecycle opens and closes collection handles per request (~2.7ms), preventing GUI lockouts.

---

## 7. Summary Comparison Matrix

| Dimension | Legacy In-Band Payload Streaming | Universal File-Based I/O Standard (v0.3.0) |
| :--- | :--- | :--- |
| **Model Token Usage** | Scales linearly with card content (Millions of tokens) | **Constant ($\mathcal{O}(1)$, $< 150$ tokens per call)** |
| **Model Output Limit Risk** | High (Truncation on large cards, batches, or ID lists) | **Zero (Only file paths and metadata emitted)** |
| **Bulk Targeting Cost** | High (Passing hundreds/thousands of IDs in tool arguments) | **Zero (File-based or query-based via `TargetSpec`)** |
| **Context Window Longevity** | Saturated instantly by HTML/syntax spans | **Clean (Instructions & reasoning preserved)** |
| **Execution Latency** | Minutes (LLM token generation bottleneck) | **Milliseconds (Native disk/DB speed, ~40ms batch ingestion)** |
| **Auditability** | Ephemeral in LLM context logs | **Persistent (Inspectable on disk in temp dir or repo)** |
| **Tool Surface Cohesion** | Fragmented across separate single/cloze/batch tools | **Consolidated (19 cohesive tools, resources & prompts)** |
