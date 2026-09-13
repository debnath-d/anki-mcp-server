# Anki Query Syntax Cheatsheet

Use these search query operators with `search_notes`, `search_cards`, `change_deck`, `set_card_state`, and `update_note_tags`.

---

## 1. Decks & Subdecks

| Query | Matches |
| :--- | :--- |
| `deck:Biology` | Cards in the "Biology" deck. |
| `deck:"Computer Science::Algorithms"` | Quotes required if deck name contains spaces or `::`. |
| `deck:CS::*` | Wildcard matches all child subdecks under "CS". |
| `-deck:Archived` | Exclude cards in the "Archived" deck. |

---

## 2. Tags

| Query | Matches |
| :--- | :--- |
| `tag:algorithms` | Cards tagged `algorithms`. |
| `tag:cs::algorithms::*` | Hierarchical wildcard match. |
| `tag:none` | Notes with no tags. |
| `-tag:leech` | Exclude cards tagged `leech`. |

---

## 3. Card State & Queue

| Query | Matches |
| :--- | :--- |
| `is:due` | Cards waiting for review today. |
| `is:new` | Unseen cards in the new queue. |
| `is:learn` | Cards currently in the learning steps. |
| `is:review` | Mature or young cards in the standard review queue. |
| `is:suspended` | Cards manually suspended from review. |

---

## 4. Review Performance & Intervals

| Query | Matches |
| :--- | :--- |
| `prop:lapses>=4` | Cards failed 4 or more times (prime candidates for leech refactoring). |
| `prop:reps>10` | Cards reviewed more than 10 times. |
| `prop:ivl>=30` | Mature cards with an interval of 30 days or greater. |
| `prop:ivl<7` | Young cards with an interval under 7 days. |
| `prop:due=0` | Cards due today. |
| `prop:due=-1` | Cards overdue by 1 day. |

---

## 5. Notes & Fields

| Query | Matches |
| :--- | :--- |
| `note:Basic` | Cards generated from the "Basic" notetype. |
| `note:Cloze` | Cards generated from the "Cloze" notetype. |
| `"Front:*recursion*"` | Notes where the `Front` field contains "recursion". |
| `w:word` | Match whole word only. |

---

## 6. Time & History

| Query | Matches |
| :--- | :--- |
| `added:1` | Notes added within the last 1 day. |
| `added:7` | Notes added within the last 7 days. |
| `rated:1` | Cards answered or reviewed within the last 1 day. |
| `rated:1:1` | Cards answered "Again" (failed) within the last 1 day. |

---

## 7. Logical Operators

* **Implicit AND (Space):** `deck:Algorithms tag:sorting is:due`
* **Explicit OR:** `tag:python OR tag:rust`
* **Negation (`-`):** `deck:Algorithms -is:suspended`
* **Grouping with Parentheses:** `deck:Physics (is:new OR is:due)`

