# Anki MCP Server Domain Context

The core domain model for the Anki Model Context Protocol (MCP) server, bridging AI assistants to local Anki flashcard collections via file-based I/O.

## Language

### Flashcard Entities

**Collection**:
The single local SQLite database (`collection.anki2`) holding all decks, notes, cards, notetypes, and review history.
_Avoid_: Database, profile store, workspace

**Deck**:
A named container (hierarchically organized via `::` delimiters) that groups cards for study sessions.
_Avoid_: Folder, category, tag group

**Notetype**:
The schema definition specifying fields, styling CSS, and card generation templates.
_Avoid_: Model, card type, template schema

**Note**:
A data record containing key-value fields and tags from which one or more cards are automatically generated.
_Avoid_: Flashcard record, card data, entry

**Card**:
A single reviewable flashcard instance generated from a note, tracked by review queues and scheduling intervals.
_Avoid_: Item, question-answer pair

**Cloze**:
A fill-in-the-blank deletion format where a single note generates multiple cards by substituting `{{cN::...}}` placeholders.
_Avoid_: Masked note, gap card

### Control & Telemetry

**Target Spec**:
A polymorphic criteria specification (explicit card IDs, note IDs, search query syntax, or disk file reference) identifying entities to act on.
_Avoid_: Filter, selection list, target query

**Telemetry**:
A bounded metadata summary (< 150 tokens) returned directly to the model with execution status, affected counts, and output file pointers.
_Avoid_: Response payload, data dump, status block
