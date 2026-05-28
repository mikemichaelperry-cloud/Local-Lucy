#!/usr/bin/env python3
"""Integrity and functional tests for the vacuum-tube database.

These tests verify:
  - Database file exists and is readable
  - Schema is correct
  - Minimum tube count (648) is present
  - No duplicate type designations
  - Case-insensitive lookup works
  - Critical tubes are present
  - Data formatting works
  - The integration into local_answer.py works end-to-end
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
sys.path.insert(0, str(Path(__file__).parent.parent.parent / "data" / "tubes"))

import sqlite3
import unittest

import tube_database
from local_answer import LocalAnswer


DB_PATH = tube_database.get_db_path()

# Tubes that MUST be present for the audio-amplifier use-case
tube_database.CRITICAL_TUBES = [
    "6V6GT", "6V6", "6L6GC", "EL34", "KT88", "6550", "KT66",
    "300B", "2A3", "845", "211",
    "12AX7", "12AT7", "12AU7", "6SN7GT", "6SL7GT", "6DJ8", "6922",
    "5U4G", "5AR4", "GZ34", "5Y3GT",
    "807", "5881", "7591", "EL84", "6BQ5",
]


class TestDatabaseFileIntegrity(unittest.TestCase):
    """Physical file and schema checks."""

    def test_database_file_exists(self):
        self.assertTrue(DB_PATH.exists(), f"Database not found at {DB_PATH}")

    def test_database_is_sqlite(self):
        with DB_PATH.open("rb") as f:
            header = f.read(16)
        self.assertTrue(header.startswith(b"SQLite format 3"))

    def test_schema_has_required_columns(self):
        conn = tube_database.init_db()
        cur = conn.execute("PRAGMA table_info(tubes)")
        columns = {row["name"] for row in cur.fetchall()}
        conn.close()
        required = {
            "id", "type", "construction", "vplate_max", "vscreen_max",
            "pplate_max", "transconductance_ma_v", "typical_push_pull_watts",
            "recommended_load_ohms", "heater_volts", "heater_amps", "notes",
        }
        self.assertTrue(required.issubset(columns), f"Missing columns: {required - columns}")

    def test_index_exists(self):
        conn = tube_database.init_db()
        cur = conn.execute("PRAGMA index_list(tubes)")
        indexes = {row["name"] for row in cur.fetchall()}
        conn.close()
        self.assertIn("idx_type", indexes)


class TestDataQuality(unittest.TestCase):
    """Content quality checks."""

    @classmethod
    def setUpClass(cls):
        cls.conn = tube_database.init_db()
        cls.all_tubes = tube_database.get_all_tubes(cls.conn)
        cls.types = [t["type"] for t in cls.all_tubes]

    @classmethod
    def tearDownClass(cls):
        cls.conn.close()

    def test_minimum_count(self):
        count = tube_database.count_tubes(self.conn)
        self.assertGreaterEqual(count, 648, f"Expected >= 648 tubes, found {count}")

    def test_no_duplicate_types(self):
        from collections import Counter
        c = Counter(self.types)
        dups = {k: v for k, v in c.items() if v > 1}
        self.assertEqual(dups, {}, f"Duplicate tube types found: {dups}")

    def test_all_tubes_have_type(self):
        for tube in self.all_tubes:
            self.assertTrue(tube["type"], f"Tube id={tube['id']} has empty type")

    def test_all_tubes_have_construction(self):
        for tube in self.all_tubes:
            self.assertTrue(tube["construction"], f"Tube {tube['type']} has empty construction")

    def test_critical_tubes_present(self):
        missing = [t for t in tube_database.CRITICAL_TUBES if t not in self.types]
        self.assertEqual(missing, [], f"Critical tubes missing: {missing}")

    def test_known_tubes_have_numeric_data(self):
        """Important audio tubes should have at least some electrical data."""
        for t in ("6V6GT", "EL34", "KT88", "300B", "12AX7"):
            tube = tube_database.lookup_tube(self.conn, t)
            self.assertIsNotNone(tube, f"{t} not found")
            self.assertTrue(
                tube["pplate_max"] is not None or tube["heater_volts"] is not None,
                f"{t} has no pplate_max or heater_volts",
            )

    def test_unknown_construction_tubes_are_minority(self):
        """Tubes marked 'unknown' should be < 20% of the database."""
        unknown = sum(1 for t in self.all_tubes if t["construction"] == "unknown")
        total = len(self.all_tubes)
        ratio = unknown / total
        self.assertLess(ratio, 0.20, f"Too many unknown tubes: {unknown}/{total} ({ratio:.1%})")


class TestLookupAndFormatting(unittest.TestCase):
    """Functional tests for lookup, search, and formatting."""

    @classmethod
    def setUpClass(cls):
        cls.conn = tube_database.init_db()

    @classmethod
    def tearDownClass(cls):
        cls.conn.close()

    def test_lookup_case_insensitive(self):
        self.assertIsNotNone(tube_database.lookup_tube(self.conn, "6v6gt"))
        self.assertIsNotNone(tube_database.lookup_tube(self.conn, "EL34"))
        self.assertIsNotNone(tube_database.lookup_tube(self.conn, "el34"))

    def test_lookup_unknown_returns_none(self):
        self.assertIsNone(tube_database.lookup_tube(self.conn, "NOTATUBE"))

    def test_search_finds_by_notes(self):
        results = tube_database.search_tubes(self.conn, "Fender")
        types = [r["type"] for r in results]
        self.assertIn("6V6GT", types)

    def test_format_tube_for_model_includes_type(self):
        tube = tube_database.lookup_tube(self.conn, "6V6GT")
        formatted = tube_database.format_tube_for_model(tube)
        self.assertIn("6V6GT", formatted)
        self.assertIn("beam power tetrode", formatted)

    def test_format_tube_skips_none_fields(self):
        tube = tube_database.lookup_tube(self.conn, "300B")
        formatted = tube_database.format_tube_for_model(tube)
        # 300B is a triode — it has no screen grid
        self.assertNotIn("screen voltage", formatted)

    def test_list_all_types_sorted(self):
        types = tube_database.list_all_types(self.conn)
        self.assertEqual(types, sorted(types))
        self.assertIn("6V6GT", types)


class TestLocalAnswerIntegration(unittest.TestCase):
    """End-to-end tests for tube lookup via LocalAnswer."""

    def setUp(self):
        self.answer = LocalAnswer()

    def tearDown(self):
        if hasattr(self, "answer") and self.answer:
            import asyncio
            try:
                asyncio.run(self.answer.close())
            except Exception:
                pass

    def test_lookup_finds_6v6gt(self):
        result = self.answer._lookup_tube_database("What are the specs of a 6V6GT?")
        self.assertIsNotNone(result)
        self.assertIn("6V6GT", result)
        self.assertIn("beam power tetrode", result)

    def test_lookup_finds_el34(self):
        result = self.answer._lookup_tube_database("Tell me about the EL34")
        self.assertIsNotNone(result)
        self.assertIn("EL34", result)

    def test_lookup_prefers_longest_match(self):
        """6V6GT should win over 6V6 when the query contains the full suffix."""
        result = self.answer._lookup_tube_database("6V6GT specifications")
        self.assertIsNotNone(result)
        self.assertTrue(result.startswith("Tube: 6V6GT"))

    def test_lookup_returns_none_for_nontube(self):
        result = self.answer._lookup_tube_database("What is Python?")
        self.assertIsNone(result)

    def test_lookup_handles_case_insensitive(self):
        result = self.answer._lookup_tube_database("kt88 push-pull specs")
        self.assertIsNotNone(result)
        self.assertIn("KT88", result)

    def test_generate_answer_short_circuits_tube(self):
        """generate_answer must return tube_database profile without calling Ollama."""
        import asyncio
        from unittest.mock import patch

        async def _test():
            with patch.object(self.answer, "_call_ollama") as mock_call:
                mock_call.side_effect = Exception("Should not be called")
                result = await self.answer.generate_answer("What are the specs of a 6V6GT?")
                self.assertFalse(mock_call.called)
                self.assertEqual(result.generation_profile, "tube_database")
                self.assertIn("6V6GT", result.text)

        asyncio.run(_test())


if __name__ == "__main__":
    unittest.main(verbosity=2)
