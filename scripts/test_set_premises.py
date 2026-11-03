"""Source-located set premise warning regressions."""

import tempfile
import unittest
from pathlib import Path

from module_check import check_module
from semantic_check import collect_semantic_diagnostics_from_text


def warnings(source, **kwargs):
    return [entry for entry in collect_semantic_diagnostics_from_text(source, **kwargs)
            if entry["code"] == "set_stmt_premise"]


class SetPremiseTests(unittest.TestCase):
    def test_plain_set_and_binding_positions(self):
        source = "{\n    | _x\n    | _x > 0\n    | _v = f(_x)\n    _v < 2\n}"
        entries = warnings(source)
        self.assertEqual([(e["lineno"], e["col_start_no"], e["col_end_no"])
                          for e in entries], [(2, 6, 12), (3, 6, 16)])
        self.assertTrue(all(e["type"] == "warning" for e in entries))

    def test_inline_separate_statements(self):
        source = "{| _x | _x > 0, _v = f(_x) | _v < 2}"
        entries = warnings(source)
        self.assertEqual(len(entries), 2)
        for entry, term in zip(entries, ["_x > 0", "_v = f(_x)"]):
            self.assertEqual(source[entry["col_start_no"]:entry["col_end_no"]], term)

    def test_image_set_explicit_premises(self):
        source = """{
    | _prev_id ∈ [0:_tail_id]
    | _s[_prev_id] = _s[_tail_id]
    => min_print_count(_s[0:_prev_id + 1]) + min_print_count(_s[_prev_id + 1:_tail_id])
}"""
        entries = warnings(source)
        self.assertEqual([e["lineno"] for e in entries], [1, 2])
        inline = "{| _x | _x ∈ xs | _v = f(_x) => _v}"
        self.assertEqual(len(warnings(inline)), 2)

    def test_no_false_positives(self):
        sources = [
            "{| _x | _x > 0}",
            "{\n    | _x\n    _x > 0\n}",
            "_xs = {1, 2}",
            "∀{| _x | _x > 0 | _x < 2}",
            "{| _x => f(_x)}",
            "{\n    | _x\n    _x ∈ xs\n    => f(_x)\n}",
            "f: _x => _y\n    | _v = f(_x)\n    _y = _v",
        ]
        for source in sources:
            with self.subTest(source=source):
                self.assertEqual(warnings(source), [])

    def test_multiline_premise_marks_first_line(self):
        source = "{\n    | _x\n    | _v = f(\n        _x)\n    _v = _x\n}"
        entries = warnings(source)
        self.assertEqual(len(entries), 1)
        self.assertEqual((entries[0]["lineno"], entries[0]["col_start_no"],
                          entries[0]["col_end_no"]), (2, 6, 13))

    def test_nested_sets_once_per_source_statement(self):
        source = "{| _x | _x ∈ {| _y | _y > 0 | _y < 3} | _x < 2}"
        self.assertEqual(len(warnings(source)), 2)
        # The image-set rewrite visits a copied nested source set as well.
        image = "{| _x | _x ∈ {| _y | _y > 0 | _y < 3} => f(_x)}"
        self.assertEqual(len(warnings(image)), 2)

    def test_import_source_positions(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp).resolve()
            imported = root / "imported.lp"
            imported.write_text("{| _x | _x > 0 | _x < 2}", encoding="utf-8")
            entries = warnings("$import imported.lp\n", file_path=root / "main.lp", base_dir=root)
            self.assertEqual(len(entries), 1)
            self.assertEqual(entries[0]["file"], str(imported))
            self.assertEqual(entries[0]["lineno"], 0)
            self.assertEqual(entries[0]["col_start_no"], 8)

    def test_warning_does_not_stop_compilation(self):
        payload = check_module("{| _x | _x > 0 | _x < 2}", "__stdin__", Path.cwd(), is_file=False)
        self.assertEqual(payload["summary"]["error_count"], 0)
        self.assertEqual(len([e for e in payload["entries"] if e["code"] == "set_stmt_premise"]), 1)


if __name__ == "__main__":
    unittest.main()
