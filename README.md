# Anki Model Context Protocol (MCP) Server

[![Python 3.10+](https://img.shields.io/badge/python-3.10+-blue.svg)](https://www.python.org/downloads/)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](https://opensource.org/licenses/MIT)

A high-performance **Model Context Protocol (MCP)** server enabling AI assistants (**Claude Desktop**, **Claude Code**, **Antigravity**, **Codex**, **Cursor**, etc.) to directly manage Anki flashcards, decks, notetypes, tags, media, and searches.

---

## ⚡ Universal File-Based I/O Architecture

Modern flashcards (especially with HTML markup, syntax-highlighted code blocks, and LaTeX math formulas) are large payloads. Streaming these through JSON-RPC tool parameters or returning full card content directly to the model causes token exhaustion, truncated outputs, and context window saturation.

This server implements **Universal File-Based Input and Output (File-Based I/O)**:

1. **Zero In-Band Token Bloat:** Flashcard mutations, queries, searches, and schema introspections accept input JSON file paths and write full structured output to disk.
2. **Compact Telemetry Responses:** Every tool call returns bounded metadata summaries ($< 150$ tokens) with status, IDs, affected counts, and the resolved `output_file` path.
3. **Atomic Batch Ingestion:** Hundreds of cards can be written to a single JSON payload and ingested in an atomic SQLite transaction in milliseconds.
4. **Cross-Platform Temp Storage:** Outputs default to the OS temporary directory (`%TEMP%\anki_mcp` on Windows, `/tmp/anki_mcp` on Linux/macOS) and can be overridden via `ANKI_MCP_OUTPUT_DIR`.

---

## Features

- **⚡ Fast Direct Bridge:** Interacts directly with Anki's collection database (`collection.anki2`) via the official `anki` Python engine with zero HTTP overhead.
- **🔒 Non-Blocking Connection Lifecycle:** Uses per-request open/close context management (~2.7ms) so database locks are immediately released and Anki Desktop is not locked out.
- **🪟 Cross-Platform:** Native support for **Windows**, **macOS**, and **Linux**, with automatic collection discovery in standard OS locations.
- **🗂️ Hierarchical Decks:** Full support for nested deck creation (e.g. `Computer Science::Algorithms::Trees`).
- **📝 Rich Card Formats:** Supports Standard/Basic cards, Cloze deletions (`{{c1::...}}`), custom fields, and LaTeX math formulas (`$...$` and `$$...$$`).
- **🔍 Query Engine:** Full support for Anki's search syntax (`deck:Languages tag:grammar`, `is:due`, `added:7`, `"Recursion"`).
- **🏷️ Tag Management:** Hierarchical tagging and bulk tag additions/removals.
- **📦 Batch Creation:** High-throughput batch card addition in single atomic operations via JSON payloads.
- **💾 Deck Export:** Native packaging to `.apkg`, `.colpkg`, and `.json`.
- **💡 MCP Prompts & Resources:** Built-in resources (`anki://decks`, `anki://stats`) and structured card generation prompt (`flashcard_generator`).

---

## Installation & Setup

This project uses [`uv`](https://github.com/astral-sh/uv) for fast, reproducible Python environment management.

### Clone and Install

```bash
git clone https://github.com/debnath-d/anki-mcp-server.git
cd anki-mcp-server
uv sync
```

### Run Server

```bash
uv run anki-mcp-server
```

---

## Client Configurations

### 1. Claude Desktop

Add the server to your Claude Desktop configuration file:

- **Windows:** `%APPDATA%\Claude\claude_desktop_config.json`
- **macOS:** `~/Library/Application Support/Claude/claude_desktop_config.json`
- **Linux:** `~/.config/Claude/claude_desktop_config.json`

#### Windows Configuration
```json
{
  "mcpServers": {
    "anki": {
      "command": "uv",
      "args": [
        "--directory",
        "C:\\path\\to\\anki-mcp-server",
        "run",
        "anki-mcp-server"
      ]
    }
  }
}
```

#### macOS / Linux Configuration
```json
{
  "mcpServers": {
    "anki": {
      "command": "uv",
      "args": [
        "--directory",
        "/path/to/anki-mcp-server",
        "run",
        "anki-mcp-server"
      ]
    }
  }
}
```

### 2. Google Antigravity

Add to your Antigravity MCP configuration (`~/.gemini/config/mcp_config.json`):

```json
{
  "mcpServers": {
    "anki": {
      "command": "uv",
      "args": [
        "--directory",
        "/path/to/anki-mcp-server",
        "run",
        "anki-mcp-server"
      ]
    }
  }
}
```

### 3. Claude Code / Codex / CLI Clients

Start Claude Code with the MCP server:

```bash
claude --mcp-server "uv --directory '/path/to/anki-mcp-server' run anki-mcp-server"
```

---

## Available MCP Tools

### 1. Deck Management

| Tool | Parameters | Description |
|------|------------|-------------|
| `list_decks` | `output_file?: str` | Lists all decks with names, IDs, and card counts. Writes hierarchy to disk and returns summary. |
| `create_deck` | `deck_name: str`, `output_file?: str` | Creates a new deck or subdeck (e.g. `Computer Science::Algorithms`). |
| `rename_deck` | `deck_id: int`, `new_name: str`, `output_file?: str` | Renames an existing deck and updates all nested subdeck prefixes. |
| `delete_deck` | `deck_id: int?`, `deck_name: str?`, `output_file?: str` | Deletes a deck and its cards. |
| `change_deck` | `target_deck_name?: str`, `card_ids?: list[int]`, `note_ids?: list[int]`, `query?: str`, `input_file?: str`, `output_file?: str` | Moves cards across decks by IDs, query, or input file. |

### 2. Notetypes (Models)

| Tool | Parameters | Description |
|------|------------|-------------|
| `list_notetypes` | `output_file?: str` | Lists all available notetypes (e.g. `Basic`, `Cloze`) and their fields to disk. |
| `get_notetype_info` | `notetype_name: str`, `output_file?: str` | Returns detailed schema, fields, and templates for a notetype to disk. |

### 3. Flashcard & Note Ingestion & Mutation (File-Based)

| Tool | Parameters | Description |
|------|------------|-------------|
| `add_notes` | `input_file: str`, `deck_name?: str`, `output_file?: str` | Ingests one or more flashcard notes (single note, cloze deletion, or batch array) atomically from a JSON payload. |
| `get_note` | `note_id: int`, `output_file?: str` | Fetches a note by ID with fields, tags, notetype, and cards to disk. |
| `update_note` | `note_id: int`, `input_file: str`, `output_file?: str` | Updates fields or tags on an existing note from a JSON payload. |
| `delete_notes` | `note_ids?: list[int]`, `input_file?: str`, `output_file?: str` | Deletes notes and their cards by ID list or JSON file. |

### 4. Media, State Control & Export

| Tool | Parameters | Description |
|------|------------|-------------|
| `store_media_file` | `source_path: str`, `target_name?: str` | Copies an image/diagram directly from disk into Anki's media storage and returns embed tags. |
| `set_card_state` | `state: str = "suspended"`, `card_ids?: list[int]`, `note_ids?: list[int]`, `query?: str`, `input_file?: str`, `output_file?: str` | Sets card review queue state (`"suspended"` or `"active"`) across target cards, notes, queries, or files. |
| `export_deck` | `deck_name: str`, `target_path: str`, `format: str = "apkg"`, `include_media: bool = True` | Exports a deck to `.apkg`, `.colpkg`, or `.json` on disk. |

### 5. Search & Discovery

| Tool | Parameters | Description |
|------|------------|-------------|
| `search_notes` | `query: str`, `limit: int = 500`, `output_file?: str` | Searches notes using Anki search syntax (`deck:Science tag:physics`, `is:due`, `"Newton"`). Writes results to disk. |
| `search_cards` | `query: str`, `limit: int = 500`, `output_file?: str` | Searches cards and returns review queue, intervals, and due dates to disk. |

### 6. Tag Management & Stats

| Tool | Parameters | Description |
|------|------------|-------------|
| `list_tags` | `output_file?: str` | Lists all unique tags across the collection to disk. |
| `update_note_tags` | `action: str = "add"`, `tags?: list[str]`, `note_ids?: list[int]`, `input_file?: str`, `output_file?: str` | Adds or removes tags in bulk across notes specified directly or within a JSON file. |
| `get_collection_stats` | `output_file?: str` | Returns summary statistics (total notes, cards, new/due cards, deck breakdown). |

---

## Testing

Run the automated test suite and linter:

```bash
ruff check .
uv run python -m unittest discover -s tests
```

---

## Important Notes & Troubleshooting

1. **SQLite Database Lock:** Anki uses exclusive file locks. The Anki desktop GUI application must be closed while the MCP server executes write operations to prevent `anki.errors.DBError` locks.
2. **Collection Path Auto-Discovery:**
   - **Windows:** Automatically detected in `%APPDATA%\Anki2\<Profile>\collection.anki2` or `%LOCALAPPDATA%\Anki2\<Profile>\collection.anki2`.
   - **macOS:** Automatically detected in `~/Library/Application Support/Anki2/<Profile>/collection.anki2`.
   - **Linux:** Automatically detected in `~/.local/share/Anki2/<Profile>/collection.anki2`.
   - To use a custom location, set the `ANKI_COLLECTION_PATH` environment variable.
3. **Output Cache:** Tool outputs are stored in your OS temporary directory (`%TEMP%\anki_mcp` or `/tmp/anki_mcp`) by default. Set `ANKI_MCP_OUTPUT_DIR` to use a custom directory.
