from __future__ import annotations

import asyncio
import contextlib
import json
import tempfile
import unittest
from pathlib import Path

from anki.errors import AnkiError, NotFoundError

from anki_mcp_server.collection import get_collection, get_default_collection_path
from anki_mcp_server.io_utils import read_json_file
from anki_mcp_server.server import (
    add_cloze_note,
    add_note,
    add_notes_batch,
    add_tags_to_notes,
    change_deck,
    create_deck,
    delete_deck,
    delete_notes,
    export_deck,
    get_collection_stats,
    get_note,
    get_notetype_info,
    list_decks,
    list_notetypes,
    list_tags,
    remove_tags_from_notes,
    rename_deck,
    search_cards,
    search_notes,
    server,
    store_media_file,
    suspend_cards,
    unsuspend_cards,
    update_note,
)


class TestAnkiMcpServer(unittest.TestCase):
    def setUp(self):
        self.test_deck = "_UnitTest_Deck"
        self.created_note_ids: list[int] = []
        self.created_media_files: list[str] = []
        self.created_decks: list[str] = [self.test_deck]
        self.temp_files: list[Path] = []

    def _create_temp_json(self, data: object) -> Path:
        with tempfile.NamedTemporaryFile(
            mode="w", suffix=".json", delete=False, encoding="utf-8"
        ) as tmp:
            json.dump(data, tmp)
            tmp_path = Path(tmp.name)
        self.temp_files.append(tmp_path)
        return tmp_path

    def tearDown(self):
        if self.created_note_ids:
            with contextlib.suppress(
                AnkiError, NotFoundError, KeyError, OSError, ValueError
            ):
                delete_notes(note_ids=self.created_note_ids)

        for d in self.created_decks:
            with contextlib.suppress(
                AnkiError, NotFoundError, KeyError, ValueError, OSError
            ):
                delete_deck(deck_name=d)

        if self.created_media_files:
            with (
                contextlib.suppress(AnkiError, NotFoundError, OSError),
                get_collection() as col,
            ):
                col.media.trash_files(self.created_media_files)
                col.media.empty_trash()

        for p in self.temp_files:
            with contextlib.suppress(OSError):
                p.unlink(missing_ok=True)

    def test_collection_path_and_connection(self):
        path = get_default_collection_path()
        self.assertTrue(path.exists())
        with get_collection(path) as col:
            self.assertIsNotNone(col)

    def test_mcp_registration(self):
        async def run_check():
            tools = await server.list_tools()
            tool_names = {t.name for t in tools}
            expected_tools = {
                "list_decks",
                "create_deck",
                "delete_deck",
                "rename_deck",
                "change_deck",
                "store_media_file",
                "suspend_cards",
                "unsuspend_cards",
                "list_notetypes",
                "get_notetype_info",
                "add_note",
                "add_cloze_note",
                "add_notes_batch",
                "get_note",
                "update_note",
                "delete_notes",
                "search_notes",
                "search_cards",
                "list_tags",
                "add_tags_to_notes",
                "remove_tags_from_notes",
                "get_collection_stats",
                "export_deck",
            }
            self.assertTrue(
                expected_tools.issubset(tool_names),
                f"Missing tools: {expected_tools - tool_names}",
            )

            resources = await server.list_resources()
            resource_uris = {r.uri for r in resources}
            self.assertIn("anki://decks", resource_uris)
            self.assertIn("anki://stats", resource_uris)

            prompts = await server.list_prompts()
            prompt_names = {p.name for p in prompts}
            self.assertIn("flashcard_generator", prompt_names)

            tool_result = await server.call_tool("list_decks", {})
            self.assertFalse(tool_result.is_error)
            self.assertTrue(len(tool_result.content) > 0)

            prompt_res = await server.get_prompt(
                "flashcard_generator",
                {"topic": "Algorithms", "concept": "Binary Search"},
            )
            self.assertTrue(len(prompt_res.messages) > 0)

        asyncio.run(run_check())

    def test_deck_management_and_rename(self):
        create_res = create_deck(self.test_deck)
        self.assertEqual(create_res["status"], "success")
        self.assertEqual(create_res["operation"], "create_deck")
        deck_id = create_res["summary"]["deck_id"]

        list_res = list_decks()
        self.assertEqual(list_res["status"], "success")
        self.assertIn("output_file", list_res)
        self.assertGreaterEqual(list_res["summary"]["deck_count"], 1)

        decks = read_json_file(list_res["output_file"])
        deck_names = [d["name"] for d in decks]
        self.assertIn(self.test_deck, deck_names)

        renamed_deck = "_UnitTest_Deck_Renamed"
        self.created_decks.append(renamed_deck)
        ren_res = rename_deck(deck_id=deck_id, new_name=renamed_deck)
        self.assertEqual(ren_res["status"], "success")
        self.assertEqual(ren_res["summary"]["new_name"], renamed_deck)

        list_res2 = list_decks()
        decks_after = read_json_file(list_res2["output_file"])
        names_after = [d["name"] for d in decks_after]
        self.assertIn(renamed_deck, names_after)
        self.assertNotIn(self.test_deck, names_after)

    def test_change_deck(self):
        source_deck = self.test_deck
        target_deck = "_UnitTest_Target_Deck"
        self.created_decks.append(target_deck)

        create_deck(source_deck)
        note_json = self._create_temp_json(
            {
                "deck_name": source_deck,
                "front": "Change Deck Question",
                "back": "Change Deck Answer",
                "tags": ["unittest", "change-deck-test"],
            }
        )
        res = add_note(input_file=str(note_json))
        nid = res["summary"]["note_id"]
        cid = res["summary"]["card_ids"][0]
        self.created_note_ids.append(nid)

        # 1. Move by card_ids
        move_res = change_deck(target_deck_name=target_deck, card_ids=[cid])
        self.assertEqual(move_res["status"], "success")
        self.assertEqual(move_res["summary"]["cards_moved"], 1)

        search_res = search_cards(f'deck:"{target_deck}"')
        cards = read_json_file(search_res["output_file"])
        self.assertEqual(len(cards), 1)
        self.assertEqual(cards[0]["card_id"], cid)

        # 2. Move by note_ids back to source_deck
        move_res2 = change_deck(target_deck_name=source_deck, note_ids=[nid])
        self.assertEqual(move_res2["status"], "success")

        # 3. Move via input_file dict JSON
        change_json = self._create_temp_json(
            {
                "target_deck_name": target_deck,
                "query": f'deck:"{source_deck}"',
            }
        )
        move_res3 = change_deck(input_file=str(change_json))
        self.assertEqual(move_res3["status"], "success")

        # 4. Move via input_file raw list JSON
        list_json = self._create_temp_json([cid])
        move_res4 = change_deck(target_deck_name=source_deck, input_file=str(list_json))
        self.assertEqual(move_res4["status"], "success")
        self.assertEqual(move_res4["summary"]["cards_moved"], 1)

    def test_store_media_file(self):
        with tempfile.NamedTemporaryFile(suffix=".png", delete=False) as tmp:
            tmp.write(b"sample fake image png data")
            tmp_path = tmp.name

        try:
            res_file = store_media_file(source_path=tmp_path)
            self.assertEqual(res_file["status"], "success")
            stored_fname = res_file["summary"]["filename"]
            self.created_media_files.append(stored_fname)
            self.assertIn("<img src=", res_file["summary"]["html_embed"])
            self.assertIn(stored_fname, res_file["summary"]["markdown_embed"])
        finally:
            Path(tmp_path).unlink(missing_ok=True)

    def test_suspend_and_unsuspend_cards(self):
        create_deck(self.test_deck)
        note_json = self._create_temp_json(
            {
                "deck_name": self.test_deck,
                "front": "Suspend Test Question",
                "back": "Suspend Test Answer",
                "tags": ["unittest", "suspend-test"],
            }
        )
        res = add_note(input_file=str(note_json))
        nid = res["summary"]["note_id"]
        cid = res["summary"]["card_ids"][0]
        self.created_note_ids.append(nid)

        sc = search_cards(f"cid:{cid}")
        cards = read_json_file(sc["output_file"])
        self.assertNotEqual(cards[0]["queue"], "suspended")

        # Suspend by card_id
        susp_res = suspend_cards(card_ids=[cid])
        self.assertEqual(susp_res["status"], "success")
        sc2 = search_cards(f"cid:{cid}")
        cards2 = read_json_file(sc2["output_file"])
        self.assertEqual(cards2[0]["queue"], "suspended")

        # Unsuspend by note_id
        unsusp_res = unsuspend_cards(note_ids=[nid])
        self.assertEqual(unsusp_res["status"], "success")
        sc3 = search_cards(f"cid:{cid}")
        cards3 = read_json_file(sc3["output_file"])
        self.assertNotEqual(cards3[0]["queue"], "suspended")

        # Suspend via input_file query
        susp_json = self._create_temp_json({"query": "tag:suspend-test"})
        susp_res2 = suspend_cards(input_file=str(susp_json))
        self.assertEqual(susp_res2["status"], "success")
        sc4 = search_cards(f"cid:{cid}")
        cards4 = read_json_file(sc4["output_file"])
        self.assertEqual(cards4[0]["queue"], "suspended")

        # Unsuspend by query
        unsusp_res2 = unsuspend_cards(query="tag:suspend-test")
        self.assertEqual(unsusp_res2["status"], "success")
        sc5 = search_cards(f"cid:{cid}")
        cards5 = read_json_file(sc5["output_file"])
        self.assertNotEqual(cards5[0]["queue"], "suspended")

    def test_suspended_note_creation(self):
        create_deck(self.test_deck)

        note_json = self._create_temp_json(
            {
                "deck_name": self.test_deck,
                "front": "Direct Suspended Front",
                "back": "Direct Suspended Back",
                "suspended": True,
            }
        )
        res = add_note(input_file=str(note_json))
        nid = res["summary"]["note_id"]
        cid = res["summary"]["card_ids"][0]
        self.created_note_ids.append(nid)
        self.assertTrue(res["summary"]["suspended"])

        sc = search_cards(f"cid:{cid}")
        cards = read_json_file(sc["output_file"])
        self.assertEqual(cards[0]["queue"], "suspended")

        cloze_json = self._create_temp_json(
            {
                "deck_name": self.test_deck,
                "text": "The Euler characteristic of a sphere is {{c1::2}}.",
                "suspended": True,
            }
        )
        cloze_res = add_cloze_note(input_file=str(cloze_json))
        cloze_nid = cloze_res["summary"]["note_id"]
        cloze_cid = cloze_res["summary"]["card_ids"][0]
        self.created_note_ids.append(cloze_nid)
        self.assertTrue(cloze_res["summary"]["suspended"])

        sc2 = search_cards(f"cid:{cloze_cid}")
        cards2 = read_json_file(sc2["output_file"])
        self.assertEqual(cards2[0]["queue"], "suspended")

    def test_notetypes(self):
        nt_res = list_notetypes()
        self.assertEqual(nt_res["status"], "success")
        notetypes = read_json_file(nt_res["output_file"])
        names = [nt["name"] for nt in notetypes]
        self.assertIn("Basic", names)
        self.assertIn("Cloze", names)

        basic_res = get_notetype_info("Basic")
        self.assertEqual(basic_res["status"], "success")
        self.assertEqual(basic_res["summary"]["name"], "Basic")
        self.assertIn("Front", basic_res["summary"]["fields"])
        self.assertIn("Back", basic_res["summary"]["fields"])

    def test_note_lifecycle(self):
        create_deck(self.test_deck)

        note_json = self._create_temp_json(
            {
                "deck_name": self.test_deck,
                "front": "What is the expected value of a standard normal distribution?",
                "back": "$$E[X] = 0$$",
                "tags": ["test::statistics", "unittest"],
            }
        )
        res = add_note(input_file=str(note_json))
        self.assertEqual(res["status"], "success")
        nid = res["summary"]["note_id"]
        self.created_note_ids.append(nid)

        note_res = get_note(nid)
        self.assertEqual(note_res["status"], "success")
        self.assertEqual(note_res["summary"]["note_id"], nid)

        note_data = read_json_file(note_res["output_file"])
        self.assertEqual(
            note_data["fields"]["Front"],
            "What is the expected value of a standard normal distribution?",
        )
        self.assertIn("test::statistics", note_data["tags"])

        update_json = self._create_temp_json(
            {
                "fields": {"Back": "$$E[X] = 0$$ (symmetric about origin)"},
                "tags": ["test::statistics", "unittest", "updated"],
            }
        )
        up_res = update_note(note_id=nid, input_file=str(update_json))
        self.assertEqual(up_res["status"], "success")
        self.assertIn("updated", up_res["summary"]["tags"])

        note_res2 = get_note(nid)
        updated_note = read_json_file(note_res2["output_file"])
        self.assertIn("symmetric", updated_note["fields"]["Back"])
        self.assertIn("updated", updated_note["tags"])

    def test_cloze_note(self):
        create_deck(self.test_deck)
        cloze_json = self._create_temp_json(
            {
                "deck_name": self.test_deck,
                "text": "The standard deviation of variance $\\sigma^2$ is {{c1::$\\sigma$}}.",
                "extra": "Basic definition",
                "tags": ["unittest", "cloze-test"],
            }
        )
        res = add_cloze_note(input_file=str(cloze_json))
        self.assertEqual(res["status"], "success")
        nid = res["summary"]["note_id"]
        self.created_note_ids.append(nid)

        note_res = get_note(nid)
        note_data = read_json_file(note_res["output_file"])
        self.assertIn("{{c1::", note_data["fields"]["Text"])

    def test_batch_notes_mixed(self):
        create_deck(self.test_deck)
        batch_json = self._create_temp_json(
            {
                "deck_name": self.test_deck,
                "notes": [
                    {
                        "front": "Standard Batch Card 1",
                        "back": "Answer 1",
                        "tags": ["unittest", "batch"],
                    },
                    {
                        "text": "Batch Cloze {{c1::Card 2}}",
                        "extra": "Explanation",
                        "is_cloze": True,
                        "tags": ["unittest", "batch", "cloze"],
                    },
                    {
                        "front": "Suspended Batch Card 3",
                        "back": "Answer 3",
                        "suspended": True,
                        "tags": ["unittest", "batch", "suspended"],
                    },
                ],
            }
        )
        res = add_notes_batch(input_file=str(batch_json))
        self.assertEqual(res["status"], "success")
        self.assertEqual(res["summary"]["total_created"], 3)

        batch_result = read_json_file(res["output_file"])
        for n in batch_result["notes"]:
            self.created_note_ids.append(n["note_id"])

        search_res = search_notes(f'deck:"{self.test_deck}" tag:batch')
        self.assertEqual(search_res["status"], "success")
        self.assertEqual(search_res["summary"]["total_matches"], 3)

        # Verify suspended card in batch
        susp_card_id = batch_result["notes"][2]["card_ids"][0]
        sc = search_cards(f"cid:{susp_card_id}")
        cards = read_json_file(sc["output_file"])
        self.assertEqual(cards[0]["queue"], "suspended")

    def test_tags_management(self):
        create_deck(self.test_deck)
        note_json = self._create_temp_json(
            {
                "deck_name": self.test_deck,
                "front": "Tag Test Question",
                "back": "Tag Test Answer",
                "tags": ["initial-tag"],
            }
        )
        res = add_note(input_file=str(note_json))
        nid = res["summary"]["note_id"]
        self.created_note_ids.append(nid)

        add_tags_to_notes(note_ids=[nid], tags=["new-tag-1", "new-tag-2"])
        note_res = get_note(nid)
        note_data = read_json_file(note_res["output_file"])
        self.assertIn("new-tag-1", note_data["tags"])
        self.assertIn("new-tag-2", note_data["tags"])

        remove_tags_from_notes(note_ids=[nid], tags=["new-tag-1"])
        note_res2 = get_note(nid)
        note_data2 = read_json_file(note_res2["output_file"])
        self.assertNotIn("new-tag-1", note_data2["tags"])
        self.assertIn("new-tag-2", note_data2["tags"])

        tag_res = list_tags()
        self.assertEqual(tag_res["status"], "success")
        all_tags = read_json_file(tag_res["output_file"])
        self.assertIn("new-tag-2", all_tags)

    def test_search_and_stats(self):
        stats_res = get_collection_stats()
        self.assertEqual(stats_res["status"], "success")
        self.assertIn("total_notes", stats_res["summary"])
        self.assertIn("total_cards", stats_res["summary"])
        self.assertIn("output_file", stats_res)

        cards_res = search_cards("is:new", limit=5)
        self.assertEqual(cards_res["status"], "success")
        self.assertIn("output_file", cards_res)

    def test_export_deck(self):
        create_deck(self.test_deck)
        note_json = self._create_temp_json(
            {
                "deck_name": self.test_deck,
                "front": "Export Test Question",
                "back": "Export Test Answer",
                "tags": ["unittest", "export-test"],
            }
        )
        res = add_note(input_file=str(note_json))
        self.created_note_ids.append(res["summary"]["note_id"])

        # 1. Export as .apkg
        with tempfile.NamedTemporaryFile(suffix=".apkg", delete=False) as tmp:
            apkg_target = tmp.name
        self.temp_files.append(Path(apkg_target))

        exp_res = export_deck(
            deck_name=self.test_deck,
            target_path=apkg_target,
            format="apkg",
            include_media=False,
        )
        self.assertEqual(exp_res["status"], "success")
        self.assertEqual(exp_res["summary"]["format"], "apkg")
        self.assertTrue(Path(apkg_target).exists())
        self.assertGreater(Path(apkg_target).stat().st_size, 0)

        # 2. Export as .colpkg
        with tempfile.NamedTemporaryFile(suffix=".colpkg", delete=False) as tmp:
            colpkg_target = tmp.name
        self.temp_files.append(Path(colpkg_target))

        exp_colpkg = export_deck(
            deck_name="all",
            target_path=colpkg_target,
            format="colpkg",
            include_media=False,
        )
        self.assertEqual(exp_colpkg["status"], "success")
        self.assertTrue(Path(colpkg_target).exists())
        self.assertGreater(Path(colpkg_target).stat().st_size, 0)

        # 3. Export as .json
        with tempfile.NamedTemporaryFile(suffix=".json", delete=False) as tmp:
            json_target = tmp.name
        self.temp_files.append(Path(json_target))

        exp_res2 = export_deck(
            deck_name=self.test_deck,
            target_path=json_target,
            format="json",
        )
        self.assertEqual(exp_res2["status"], "success")
        self.assertEqual(exp_res2["summary"]["format"], "json")
        self.assertTrue(Path(json_target).exists())
        json_data = read_json_file(json_target)
        self.assertEqual(len(json_data), 1)
        self.assertEqual(json_data[0]["note_id"], res["summary"]["note_id"])

    def test_negative_validations(self):
        # 1. Non-existent deck deletion by name
        with self.assertRaises(ValueError):
            delete_deck(deck_name="_Definitely_Non_Existent_Deck_12345_")

        # 2. Delete deck without args
        with self.assertRaises(ValueError):
            delete_deck()

        # 3. Invalid notetype in add_note
        invalid_nt_json = self._create_temp_json(
            {
                "deck_name": self.test_deck,
                "front": "Q",
                "back": "A",
                "notetype_name": "_NonExistentNotetype_9999_",
            }
        )
        with self.assertRaises(ValueError):
            add_note(input_file=str(invalid_nt_json))

        # 4. Invalid field on notetype
        invalid_field_json = self._create_temp_json(
            {
                "deck_name": self.test_deck,
                "fields": {"NonExistentField": "Value"},
                "notetype_name": "Basic",
            }
        )
        with self.assertRaises(ValueError):
            add_note(input_file=str(invalid_field_json))

        # 5. Empty change_deck criteria
        with self.assertRaises(ValueError):
            change_deck(target_deck_name=self.test_deck)

        # 6. Malformed JSON file
        with tempfile.NamedTemporaryFile(mode="w", suffix=".json", delete=False) as tmp:
            tmp.write("{ invalid json")
            bad_path = tmp.name
        self.temp_files.append(Path(bad_path))

        with self.assertRaises(ValueError):
            read_json_file(bad_path)

        # 7. Missing file
        with self.assertRaises(FileNotFoundError):
            read_json_file("/non/existent/path/file.json")

    def test_windows_path_resolution(self):
        from unittest.mock import patch

        with tempfile.TemporaryDirectory() as temp_appdata:
            mock_anki_dir = Path(temp_appdata) / "Anki2" / "User 1"
            mock_anki_dir.mkdir(parents=True)
            mock_col = mock_anki_dir / "collection.anki2"
            mock_col.touch()

            with (
                patch.dict(
                    "os.environ",
                    {"APPDATA": temp_appdata, "ANKI_COLLECTION_PATH": ""},
                    clear=False,
                ),
                patch(
                    "pathlib.Path.home",
                    return_value=Path(temp_appdata) / "NonExistentHome",
                ),
            ):
                resolved = get_default_collection_path()
                self.assertEqual(resolved, mock_col)


if __name__ == "__main__":
    unittest.main()
