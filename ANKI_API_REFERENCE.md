# Anki Python API Reference — `anki`

> Comprehensive guide to programmatically creating and managing Anki flashcards
> via the `anki` Python module.

---

## Table of Contents

1. [Project Directory Structure](#project-directory-structure)
2. [Core Concepts](#core-concepts)
3. [Opening the Collection](#opening-the-collection)
4. [Decks](#decks)
5. [Notetypes (Models)](#notetypes-models)
6. [Creating Notes (Flashcards)](#creating-notes-flashcards)
7. [Reading & Updating Notes](#reading--updating-notes)
8. [Searching for Notes/Cards](#searching-for-notescards)
9. [Tags](#tags)
10. [Deleting Notes & Cards](#deleting-notes--cards)
11. [Batch Operations](#batch-operations)
12. [Cards (Lower-Level)](#cards-lower-level)
13. [Import / Export](#import--export)
14. [Database Access (Escape Hatch)](#database-access-escape-hatch)
15. [Caveats & Best Practices](#caveats--best-practices)
16. [Stock Notetype Kinds](#stock-notetype-kinds)
17. [Constants Reference](#constants-reference)

---

## Project Directory Structure

```
anki_mcp_server/
├── pyproject.toml            # Project metadata (depends on anki>=26.8.1, mcp[cli]>=2.0.0)
├── uv.lock                   # uv lockfile
├── README.md                 # Server documentation and MCP client configs
├── tests/
│   └── test_server.py        # Automated test suite
└── src/
    └── anki_mcp_server/
        ├── __init__.py       # Package init (defines main() entry point for MCP stdio)
        ├── collection.py     # Safe connection lifecycle manager & path resolution
        ├── io_utils.py       # File-based I/O utilities & JSON helpers
        └── server.py         # MCP server with tools, prompts, and resources
```

### Key Files

| File | Purpose |
|------|---------|
| `src/anki_mcp_server/server.py` | MCP server implementation exposing Anki tools (`add_note`, `list_decks`, `change_deck`, etc.), prompts, and resources to AI assistants. |
| `src/anki_mcp_server/collection.py` | Connection lifecycle context manager (`get_collection()`). Resolves collection path across Windows, macOS, and Linux, ensuring exclusive SQLite locks are immediately released after each operation. |
| `src/anki_mcp_server/io_utils.py` | Cross-platform temporary file and output handling for token-efficient File-Based I/O. |
| `src/anki_mcp_server/__init__.py` | Package init. Defines CLI entry point `main()` to launch the MCP server over stdio (`server.run(transport="stdio")`). |

### Running

```bash
cd /path/to/anki_mcp_server
uv run anki-mcp-server
# or directly via python module:
uv run python -m anki_mcp_server
```

> **⚠️ CRITICAL:** Anki desktop GUI must be closed before running any script or MCP tool
> that opens the collection. The SQLite database uses an exclusive lock — two processes cannot
> open it simultaneously.

---

## Core Concepts

### Note vs Card

This is the single most important distinction in Anki's data model:

| Concept | What It Is | Example |
|---------|-----------|---------|
| **Note** | A set of *fields* with a *notetype*. A single unit of knowledge. | Front: "What is an AVL tree?" / Back: "A self-balancing binary search tree..." |
| **Card** | A single *review unit* generated from a note + a *template*. | The front→back flashcard you actually review. |
| **Notetype** (Model) | Defines the fields and card templates for a note. | "Basic" has fields [Front, Back] and 1 template. "Basic (and reversed card)" produces 2 cards per note. |
| **Deck** | A container for cards (not notes). Cards are assigned to decks. | "Computer Science::Algorithms", "Languages::Spanish" |
| **Template** | An HTML template within a notetype that produces one card per note. | `{{Front}}` on question side, `{{FrontSide}}<hr>{{Back}}` on answer side. |

A note with a "Basic (and reversed card)" notetype produces **2 cards**: one front→back, one back→front.

### Hierarchical Decks

Decks support `::` separators for nesting:
- `Computer Science` — top-level deck
- `Computer Science::Algorithms` — sub-deck
- `Computer Science::Algorithms::Trees` — sub-sub-deck

Creating a deck with `::` in the name automatically creates parent decks.

### IDs

All objects use integer IDs (epoch-millisecond timestamps at creation):
- `NoteId` — identifies a note
- `CardId` — identifies a card
- `NotetypeId` — identifies a notetype
- `DeckId` — identifies a deck

---

## Opening the Collection

```python
from pathlib import Path
from anki.collection import Collection

# Example Linux / macOS path
COLLECTION_PATH = (
    Path.home() / ".local" / "share" / "Anki2" / "User 1" / "collection.anki2"
)
# Example Windows path
# COLLECTION_PATH = Path(os.environ["APPDATA"]) / "Anki2" / "User 1" / "collection.anki2"

col = Collection(str(COLLECTION_PATH))

# ... do work ...

col.close()  # ALWAYS close when done
```

The `Collection` constructor:
1. Takes an absolute path to the `.anki2` file (string).
2. Optionally accepts a `backend` (`RustBackend`) or `server` flag.
3. Automatically opens the database, initializes managers:
   - `col.models` — `ModelManager` (notetypes)
   - `col.decks` — `DeckManager`
   - `col.tags` — `TagManager`
   - `col.conf` — `ConfigManager`
   - `col.media` — `MediaManager`
   - `col.sched` — Scheduler (v3 by default)
   - `col.db` — `DBProxy` for raw SQL
4. Saving is **automatic** — no need to call `col.save()`.

> **Important:** Always call `col.close()` when done. Use a context manager
> pattern or try/finally block to ensure cleanup.

---

## Decks

Managed via `col.decks` (`DeckManager`).

### Create a Deck

```python
from anki.decks import DeckId

# Method 1: Simple — create by name, returns DeckId (idempotent)
deck_id = col.decks.id("Computer Science::Algorithms")

# Method 2: Preferred modern API
from anki.collection import OpChangesWithId

result: OpChangesWithId = col.decks.add_normal_deck_with_name(
    "Computer Science::Data Structures"
)
deck_id = DeckId(result.id)
```

### Find a Deck by Name

```python
deck_id = col.decks.id_for_name("Computer Science::Algorithms")  # DeckId | None
deck_dict = col.decks.by_name("Computer Science::Algorithms")  # DeckDict | None
```

### List All Decks

```python
# Efficient: just names and IDs
for entry in col.decks.all_names_and_ids():
    print(f"{entry.name} (id={entry.id})")

# Full deck objects (expensive)
all_decks = col.decks.all()
```

### Get a Deck

```python
deck = col.decks.get(deck_id)  # DeckDict | None
deck = col.decks.get_legacy(deck_id)  # DeckDict | None
```

### Rename a Deck

```python
col.decks.rename(deck_id, "Computer Science::Advanced Algorithms")
```

### Delete a Deck

```python
col.decks.remove([deck_id])
```

### Deck Hierarchy

```python
# Get children of a deck
children = col.decks.children(deck_id)  # list of (name, DeckId)

# Parse hierarchy
parts = col.decks.path("Computer Science::Algorithms::Trees")
# → ["Computer Science", "Algorithms", "Trees"]
```

---

## Notetypes (Models)

Managed via `col.models` (`ModelManager`). A notetype defines:
- **Fields** (e.g., `Front`, `Back`, `Extra`)
- **Templates** (card HTML with `{{field}}` placeholders)
- **CSS** styling

### Get an Existing Notetype

```python
from anki.models import NotetypeId

# By name
notetype = col.models.by_name("Basic")

# By ID
notetype = col.models.get(NotetypeId(1234567890123))

# Get ID from name
nt_id = col.models.id_for_name("Basic")  # NotetypeId | None
```

### List All Notetypes

```python
# Names and IDs (cheap)
for nt in col.models.all_names_and_ids():
    print(f"{nt.name} (id={nt.id})")

# With use counts
for nt in col.models.all_use_counts():
    print(f"{nt.name}: {nt.use_count} notes")
```

### Create a Custom Notetype

```python
# Start from scratch
notetype = col.models.new("Concept Q&A")

# Add fields
front_field = col.models.new_field("Question")
col.models.add_field(notetype, front_field)

back_field = col.models.new_field("Answer")
col.models.add_field(notetype, back_field)

source_field = col.models.new_field("Source")
col.models.add_field(notetype, source_field)

topic_field = col.models.new_field("Topic")
col.models.add_field(notetype, topic_field)

# Add a template (produces one card per note)
template = col.models.new_template("Card 1")
template["qfmt"] = """
<div class="topic">{{Topic}}</div>
<div class="question">{{Question}}</div>
"""
template["afmt"] = """
{{FrontSide}}
<hr id=answer>
<div class="answer">{{Answer}}</div>
<div class="source">{{Source}}</div>
"""
col.models.add_template(notetype, template)

# Optional: add CSS
notetype["css"] = """
.card { font-family: 'Inter', sans-serif; font-size: 16px; }
.topic { color: #888; font-size: 12px; margin-bottom: 8px; }
.question { font-weight: 600; }
.source { color: #666; font-style: italic; margin-top: 12px; }
"""

# Save to collection
col.models.add(notetype)
# notetype["id"] is now populated with the new ID
```

### Modify a Notetype

```python
# Fetch, modify, save
notetype = col.models.by_name("Concept Q&A")
notetype["css"] += "\n.answer { line-height: 1.6; }\n"
col.models.update_dict(notetype)
```

### Field Operations

```python
# Get field names
names = col.models.field_names(notetype)  # ["Question", "Answer", "Source", "Topic"]

# Get field map: name → (ordinal, FieldDict)
fmap = col.models.field_map(notetype)

# Add a field to an existing notetype (modifies schema!)
new_field = col.models.new_field("Difficulty")
col.models.add_field(notetype, new_field)
col.models.update_dict(notetype)

# Rename a field
col.models.rename_field(notetype, notetype["flds"][2], "Reference")
col.models.update_dict(notetype)
```

### Notetype Dict Structure

A `NotetypeDict` is a plain dict with these key fields:

```python
{
    "id": 1234567890123,       # NotetypeId
    "name": "Concept Q&A",
    "type": 0,                 # MODEL_STD=0, MODEL_CLOZE=1
    "flds": [                  # List of FieldDicts
        {"name": "Question", "ord": 0, ...},
        {"name": "Answer",   "ord": 1, ...},
    ],
    "tmpls": [                 # List of TemplateDicts
        {
            "name": "Card 1",
            "qfmt": "{{Question}}",     # Question format (HTML)
            "afmt": "{{FrontSide}}\n<hr>\n{{Answer}}",  # Answer format
            "ord": 0,
        },
    ],
    "css": ".card { ... }",    # Shared CSS for all templates
    "sortf": 0,                # Index of sort field
    ...
}
```

---

## Creating Notes (Flashcards)

This is the primary operation: creating a **note** adds it to the collection, and cards are **automatically generated** from its notetype's templates.

### Add a Single Note

```python
from anki.decks import DeckId

# 1. Get or create the deck
deck_id = col.decks.id("Computer Science::Algorithms")

# 2. Get the notetype
notetype = col.models.by_name("Basic")  # or your custom "Concept Q&A"

# 3. Create the note object
note = col.new_note(notetype)

# 4. Fill in the fields (dict-like interface)
note["Front"] = "What is the average and worst-case time complexity of QuickSort?"
note["Back"] = r"""
- **Average case:** $\mathcal{O}(n \log n)$
- **Worst case:** $\mathcal{O}(n^2)$ (when pivot selection is poor on sorted arrays)
"""

# 5. Add tags
note.tags = ["algorithms", "sorting", "computer-science"]

# 6. Add to collection
col.add_note(note, deck_id)

# note.id is now set to the new NoteId
print(f"Created note {note.id}")
```

### Add Multiple Notes (Batch)

```python
from anki.collection import AddNoteRequest

requests = []

cards_data = [
    {
        "front": "Define a bipartite graph.",
        "back": "A graph whose vertices can be divided into two disjoint sets U and V such that every edge connects a vertex in U to one in V.",
        "tags": ["graph-theory", "discrete-math"],
    },
    {
        "front": "State the Master Theorem for divide-and-conquer recurrences.",
        "back": "For $T(n) = aT(n/b) + f(n)$, compare $f(n)$ to $n^{\\log_b a}$...",
        "tags": ["algorithms", "asymptotics"],
    },
]

notetype = col.models.by_name("Basic")
deck_id = col.decks.id("Computer Science::Algorithms")

for data in cards_data:
    note = col.new_note(notetype)
    note["Front"] = data["front"]
    note["Back"] = data["back"]
    note.tags = data["tags"]
    requests.append(AddNoteRequest(note=note, deck_id=deck_id))

col.add_notes(requests)

# Each note now has its .id populated
for req in requests:
    print(f"Created note {req.note.id}")
```

### Using the Cloze Notetype

For fill-in-the-blank style cards:

```python
cloze_type = col.models.by_name("Cloze")
note = col.new_note(cloze_type)
note["Text"] = (
    "In Dijkstra's algorithm, the priority queue extracts the vertex with "
    "the {{c1::minimum distance}} in {{c2::$\\mathcal{O}(\\log V)$}} time."
)
note.tags = ["algorithms", "graphs", "dijkstra"]
col.add_note(note, col.decks.id("Computer Science::Algorithms"))
# This creates 2 separate cards (one per cloze deletion)
```

---

## Reading & Updating Notes

### Read a Note by ID

```python
from anki.notes import NoteId

note = col.get_note(NoteId(1234567890123))
print(note["Front"])  # Read a field
print(note.tags)  # List of tag strings
print(note.fields)  # List of all field values (by ordinal)
print(note.items())  # List of (field_name, value) tuples
```

### Update a Note

```python
note = col.get_note(note_id)
note["Back"] = "Updated answer with better explanation..."
note.add_tag("revised")
col.update_note(note)  # Saves to DB with undo entry
```

### Update Multiple Notes

```python
notes_to_update = []
for nid in note_ids:
    note = col.get_note(nid)
    note.add_tag("reviewed-2026")
    notes_to_update.append(note)

col.update_notes(notes_to_update)
```

### Note Properties

```python
note.id  # NoteId
note.mid  # NotetypeId (model id)
note.guid  # Globally unique ID string
note.tags  # list[str]
note.fields  # list[str] — raw field values by ordinal
note.mod  # Modification time (epoch seconds)

# Dict-like access by field name
note["Front"]  # Get field value
note["Front"] = "new"  # Set field value
note.keys()  # List of field names
note.items()  # List of (name, value) tuples

# Related objects
note.note_type()  # NotetypeDict
note.cards()  # list[Card] — all cards generated from this note
note.card_ids()  # Sequence[CardId]

# Tag operations
note.has_tag("probability")
note.add_tag("hard")
note.remove_tag("easy")
note.set_tags_from_str("tag1 tag2 tag3")
note.string_tags()  # → " tag1 tag2 tag3 "

# Validation
note.fields_check()  # Check for empty/duplicate first field
```

---

## Searching for Notes/Cards

The search syntax mirrors Anki's browser search bar.

### Find Card IDs

```python
# By tag
card_ids = col.find_cards("tag:algorithms")

# By deck
card_ids = col.find_cards("deck:Computer Science::Algorithms")

# By field content
card_ids = col.find_cards('"QuickSort"')

# By notetype
card_ids = col.find_cards("note:Basic")

# Combinations
card_ids = col.find_cards("deck:Computer Science tag:hard -tag:suspended")

# New / due / review status
card_ids = col.find_cards("is:new")
card_ids = col.find_cards("is:due")
card_ids = col.find_cards("is:review")

# Added in last 7 days
card_ids = col.find_cards("added:7")

# With ordering
card_ids = col.find_cards(
    "deck:Computer Science", order=True
)  # collection default sort
card_ids = col.find_cards(
    "deck:Computer Science", order="c.due asc"
)  # custom SQL order
```

### Find Note IDs

```python
note_ids = col.find_notes("tag:algorithms")
note_ids = col.find_notes("deck:Computer Science::Algorithms")
note_ids = col.find_notes('"binary search"')
```

### Build Search Strings Programmatically

```python
from anki.collection import SearchNode

# Using SearchNode for type-safe queries
query = col.build_search_string(
    SearchNode(deck="Computer Science"),
    SearchNode(tag="algorithms"),
)
# → '"deck:Computer Science" "tag:algorithms"'

# OR queries
query = col.build_search_string(
    SearchNode(tag="algorithms"),
    SearchNode(tag="data-structures"),
    joiner="OR",
)

# Negation
negated = SearchNode(negated=col.group_searches(SearchNode(tag="suspended")))
query = col.build_search_string(
    SearchNode(deck="Computer Science"),
    negated,
)
```

### Find and Replace in Fields

```python
col.find_and_replace(
    note_ids=note_ids,
    search="O(n)",
    replacement="$\\mathcal{O}(n)$",
    regex=False,
    field_name="Back",  # None = all fields
    match_case=False,
)
```

### Find Duplicates

```python
dupes = col.find_dupes("Front")  # → list of ("duplicate_text", [nid1, nid2, ...])
```

---

## Tags

Managed via `col.tags` (`TagManager`). Tags are space-separated strings on notes and support `::` hierarchy.

### List All Tags

```python
all_tags = col.tags.all()  # list[str]
tag_tree = col.tags.tree()  # TagTreeNode (hierarchical)
```

### Add/Remove Tags in Bulk

```python
# Add tags to multiple notes at once
col.tags.bulk_add(note_ids, "computer-science algorithms")

# Remove tags from multiple notes
col.tags.bulk_remove(note_ids, "easy")
```

### Rename Tags

```python
# Rename a tag (and its children) across all notes
col.tags.rename("algo", "algorithms")
```

### Remove Unused Tags

```python
col.tags.clear_unused_tags()
```

### Tag Utilities

```python
col.tags.split("tag1 tag2 tag3")  # → ["tag1", "tag2", "tag3"]
col.tags.join(["tag1", "tag2"])  # → " tag1 tag2 "
col.tags.in_list("algorithms", ["Algorithms", "cs"])  # → True (case-insensitive)
```

### Hierarchical Tags Example

Recommended hierarchical tag patterns:

```
subject::computer-science
subject::computer-science::algorithms
subject::computer-science::data-structures
subject::mathematics::linear-algebra
difficulty::easy
difficulty::medium
difficulty::hard
```

---

## Deleting Notes & Cards

### Remove Notes (and Their Cards)

```python
col.remove_notes(note_ids)  # Deletes notes AND all generated cards
```

### Remove Cards (Keep Orphaned Notes)

```python
col.remove_cards_and_orphaned_notes(card_ids)
```

### Remove Notes by Card IDs

```python
col.remove_notes_by_card(card_ids)  # Deletes the parent notes too
```

---

## Batch Operations

### Batch Add with Different Decks

```python
from anki.collection import AddNoteRequest

requests = []

# Algorithms cards
nt = col.models.by_name("Basic")
algo_deck = col.decks.id("Computer Science::Algorithms")
note1 = col.new_note(nt)
note1["Front"] = "What is the time complexity of MergeSort?"
note1["Back"] = "$\\mathcal{O}(n \\log n)$ in all cases"
note1.tags = ["algorithms", "sorting"]
requests.append(AddNoteRequest(note=note1, deck_id=algo_deck))

# Linear algebra cards
math_deck = col.decks.id("Mathematics::Linear Algebra")
note2 = col.new_note(nt)
note2["Front"] = "What are the eigenvalues of an identity matrix $I_n$?"
note2["Back"] = "All eigenvalues are $\\lambda = 1$ with algebraic multiplicity $n$."
note2.tags = ["math", "linear-algebra"]
requests.append(AddNoteRequest(note=note2, deck_id=math_deck))

col.add_notes(requests)
```

### Move Cards Between Decks

```python
target_deck_id = col.decks.id("Computer Science::Advanced Topics")
card_ids = col.find_cards("tag:hard deck:Computer Science::Algorithms")
col.set_deck(card_ids, target_deck_id)
```

---

## Cards (Lower-Level)

Most operations work at the **note** level. Cards are auto-generated from notes. But you can access them when needed.

### Get a Card

```python
from anki.cards import CardId

card = col.get_card(CardId(1234567890123))
```

### Card Properties

```python
card.id  # CardId
card.nid  # NoteId — parent note
card.did  # DeckId — which deck this card is in
card.ord  # Template ordinal (0 = first template)
card.type  # CardType: 0=new, 1=learning, 2=review, 3=relearning
card.queue  # CardQueue: 0=new, 1=learn, 2=review, -1=suspended, -2/-3=buried
card.due  # Due date/position (meaning depends on queue)
card.ivl  # Current interval in days
card.factor  # Ease factor (2500 = 250%)
card.reps  # Number of reviews
card.lapses  # Number of lapses (times forgotten)

# Rendered content
card.question()  # Rendered question HTML
card.answer()  # Rendered answer HTML

# Related objects
card.note()  # Parent Note
card.note_type()  # NotetypeDict
card.template()  # TemplateDict
```

### Update a Card

```python
card = col.get_card(card_id)
card.did = new_deck_id
col.update_card(card)
```

---

## Import / Export

### Import CSV

```python
from anki.collection import ImportCsvRequest

path = "/path/to/flashcards.csv"
metadata = col.get_csv_metadata(path=path, delimiter=None)  # auto-detect
request = ImportCsvRequest(path=path, metadata=metadata)
response = col.import_csv(request)
print(f"Found: {response.log.found_notes}")
```

### Import JSON

```python
col.import_json_file("/path/to/data.json")
col.import_json_string('{"notes": [...]}')
```

### Export

```python
from anki.collection import ExportAnkiPackageOptions, DeckIdLimit

# Export a deck as .apkg
col.export_anki_package(
    out_path="/tmp/exported_deck.apkg",
    options=ExportAnkiPackageOptions(with_media=True),
    limit=DeckIdLimit(deck_id=deck_id),
)

# Export notes as CSV
col.export_note_csv(
    out_path="/tmp/exported_notes.csv",
    limit=DeckIdLimit(deck_id=deck_id),
    with_html=False,
    with_tags=True,
    with_deck=True,
    with_notetype=True,
    with_guid=False,
)
```

---

## Database Access (Escape Hatch)

> **⚠️ WARNING:** Direct DB writes **will not sync** and can corrupt data.
> Prefer the Python API methods above. Use DB access only for **read-only
> queries**.

```python
# Scalar (single value)
count = col.db.scalar("select count() from notes")

# List (first column)
ids = col.db.list("select id from notes limit 10")

# All rows
rows = col.db.all("select id, flds from notes limit 5")

# Iterate without building list
for nid, flds in col.db.execute("select id, flds from notes limit 5"):
    print(nid, flds[:50])

# Write (NOT recommended — won't sync)
# col.db.execute("update cards set ivl = ? where id = ?", new_ivl, card_id)
```

---

## Caveats & Best Practices

### 1. Close Anki Desktop First

The collection database uses an exclusive SQLite lock. You **cannot** run scripts while Anki is open:

```python
# Good pattern:
try:
    col = Collection(str(COLLECTION_PATH))
    # ... do work ...
finally:
    col.close()
```

### 2. Use Python API, Not Raw SQL

Always prefer `col.add_note()`, `col.update_note()`, `col.decks.add_normal_deck_with_name()` etc. over direct DB access. The API:
- Marks items for sync
- Validates data integrity
- Creates proper undo entries
- Generates cards from templates

### 3. Fields Are HTML

Note field values are stored as **HTML**. For LaTeX/MathJax:
```python
note["Back"] = r"The answer is \(\frac{1}{2}\)"  # MathJax inline
note["Back"] = r"$$E[X] = \sum x \cdot P(X=x)$$"  # MathJax display
```

### 4. Saving Is Automatic

You do **not** need to call `col.save()` — it's deprecated. All operations auto-commit.

### 5. Check for Duplicates

Before adding notes, check if the first field already exists:

```python
note = col.new_note(notetype)
note["Front"] = "What is an AVL tree?"
result = note.fields_check()
# result is a NoteFieldsCheckResult enum:
#   NORMAL = 0 (ok)
#   EMPTY = 1 (first field empty)
#   DUPLICATE = 2 (duplicate of existing note)
```

### 6. Idempotent Deck Creation

`col.decks.id("name")` returns the existing deck ID if it exists, or creates it. Safe to call repeatedly.

### 7. Notetype Caching

`col.models.get()` returns a **cached reference**. If you modify it, you must save it with `col.models.update_dict()`. If you want to modify without affecting the cache, `copy.deepcopy()` first.

---

## Stock Notetype Kinds

Available via `StockNotetypeKind`:

| Kind | Description | Fields | Cards per Note |
|------|-------------|--------|---------------|
| `KIND_BASIC` | Front → Back | Front, Back | 1 |
| `KIND_BASIC_AND_REVERSED` | Both directions | Front, Back | 2 |
| `KIND_BASIC_OPTIONAL_REVERSED` | Front→Back + optional reverse | Front, Back, Add Reverse | 1 or 2 |
| `KIND_BASIC_TYPING` | Type the answer | Front, Back | 1 |
| `KIND_CLOZE` | Fill-in-the-blank | Text, Back Extra | 1 per `{{cN::...}}` |
| `KIND_IMAGE_OCCLUSION` | Image with hidden regions | Image, ... | variable |

### Getting a Stock Notetype

```python
from anki.stdmodels import StockNotetypeKind
from anki.utils import from_json_bytes

basic = from_json_bytes(
    col._backend.get_stock_notetype_legacy(StockNotetypeKind.KIND_BASIC)
)
```

---

## Constants Reference

From `anki.consts`:

### Card Types (`CardType`)

| Constant | Value | Meaning |
|----------|-------|---------|
| `CARD_TYPE_NEW` | 0 | Never reviewed |
| `CARD_TYPE_LRN` | 1 | Currently learning |
| `CARD_TYPE_REV` | 2 | Review (graduated) |
| `CARD_TYPE_RELEARNING` | 3 | Re-learning (lapsed) |

### Queue Types (`CardQueue`)

| Constant | Value | Meaning |
|----------|-------|---------|
| `QUEUE_TYPE_NEW` | 0 | New card queue |
| `QUEUE_TYPE_LRN` | 1 | Learning queue |
| `QUEUE_TYPE_REV` | 2 | Review queue |
| `QUEUE_TYPE_DAY_LEARN_RELEARN` | 3 | Day (re)learn |
| `QUEUE_TYPE_SUSPENDED` | -1 | Suspended |
| `QUEUE_TYPE_SIBLING_BURIED` | -2 | Buried by sibling |
| `QUEUE_TYPE_MANUALLY_BURIED` | -3 | Manually buried |

### Model Types

| Constant | Value | Meaning |
|----------|-------|---------|
| `MODEL_STD` | 0 | Standard notetype |
| `MODEL_CLOZE` | 1 | Cloze notetype |

---

## Example Hierarchical Deck Structure

```
Computer Science
├── Algorithms
│   ├── Sorting & Searching
│   ├── Graph Algorithms
│   ├── Dynamic Programming
│   └── Greedy Algorithms
├── Data Structures
│   ├── Trees & Graphs
│   ├── Hash Tables
│   └── Heaps
├── Systems & Architecture
│   ├── Operating Systems
│   ├── Networking
│   └── Concurrency
└── Mathematics for CS
    ├── Discrete Mathematics
    ├── Linear Algebra
    └── Probability & Statistics
```

---

## Quick-Start Recipe: Adding Your First Batch

```python
from pathlib import Path
from anki.collection import Collection, AddNoteRequest

# Replace with your collection path (or use anki_mcp_server.collection.get_collection())
COL_PATH = Path.home() / ".local/share/Anki2/User 1/collection.anki2"

col = Collection(str(COL_PATH))

try:
    # Ensure deck exists
    deck_id = col.decks.id("Computer Science::Algorithms")

    # Get or use Basic notetype
    nt = col.models.by_name("Basic")

    # Prepare cards
    cards = [
        (
            "What is the time complexity of binary search?",
            "$\\mathcal{O}(\\log n)$ on a sorted array.",
        ),
        (
            "What data structure is typically used for Breadth-First Search (BFS)?",
            "A Queue (FIFO).",
        ),
    ]

    requests = []
    for front, back in cards:
        note = col.new_note(nt)
        note["Front"] = front
        note["Back"] = back
        note.tags = ["computer-science", "algorithms"]
        requests.append(AddNoteRequest(note=note, deck_id=deck_id))

    col.add_notes(requests)
    print(f"Added {len(requests)} notes to deck {deck_id}")

finally:
    col.close()
```
