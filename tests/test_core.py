import io
import json
import subprocess
import sys
import unittest

from pgcopy_lint.core import audit, unescape


class CopyTests(unittest.TestCase):
    def check(self, data, columns=2, **kwargs):
        return audit(io.BytesIO(data), columns, **kwargs)

    def codes(self, result):
        return {item["code"] for item in result["issues"]}

    def test_plain_and_empty_values(self):
        r = self.check(b"a\tb\n\t\n")
        self.assertTrue(r["ok"])
        self.assertEqual((r["records"], r["fields"]), (2, 4))

    def test_empty_file_is_zero_rows(self):
        r = self.check(b"")
        self.assertTrue(r["ok"])
        self.assertEqual(r["records"], 0)

    def test_empty_line_is_one_empty_field(self):
        self.assertTrue(self.check(b"\n", 1)["ok"])
        self.assertIn("field-count", self.codes(self.check(b"\n")))

    def test_null_before_unescape(self):
        r = self.check(b"\\N\t\\\\N\n")
        self.assertTrue(r["ok"])
        self.assertEqual(r["null_fields"], 1)
        r = self.check(b"\\000\tvalue\n", null=b"\\000")
        self.assertTrue(r["ok"])
        self.assertEqual(r["null_fields"], 1)

    def test_utf8(self):
        self.assertTrue(self.check("雪\t🙂\n".encode())["ok"])

    def test_custom_delimiter(self):
        self.assertTrue(self.check(b"a\\|b|c\n", delimiter=b"|")["ok"])

    def test_hex_and_octal_utf8(self):
        for data in [b"\\xC3\\xA9\tx\n", b"\\303\\251\tx\n"]:
            self.assertTrue(self.check(data)["ok"])

    def test_decoded_nul_and_bad_utf8(self):
        for value, code in [
            (b"\\0", "nul-after-unescape"),
            (b"\\x00", "nul-after-unescape"),
            (b"\\400", "nul-after-unescape"),
            (b"\\xff", "invalid-decoded-utf8"),
        ]:
            with self.subTest(value=value):
                self.assertIn(code, self.codes(self.check(value + b"\tx\n")))

    def test_invalid_raw_encoding_and_nul(self):
        r = self.check(b"\xff\t\0\n")
        self.assertIn("invalid-input-utf8", self.codes(r))
        self.assertIn("nul-in-input", self.codes(r))

    def test_escaped_delimiter_is_not_separator(self):
        self.assertTrue(self.check(b"a\\\tb\tx\n")["ok"])

    def test_even_and_odd_backslashes(self):
        self.assertTrue(self.check(b"a\\\\\tb\n")["ok"])
        self.assertFalse(self.check(b"a\\\tb\n")["ok"])

    def test_literal_newline_escape_warns(self):
        r = self.check(b"a\\\nb\tx\n")
        self.assertTrue(r["ok"])
        self.assertEqual(r["records"], 1)
        self.assertIn("literal-newline-escape", self.codes(r))

    def test_unknown_escape_warns_without_changing_grammar(self):
        r = self.check(b"C:\\path\tx\n")
        self.assertTrue(r["ok"])
        self.assertIn("unknown-escape", self.codes(r))
        self.assertEqual(unescape(b"\\xZ", 9)[0], b"xZ")

    def test_trailing_backslash_warns(self):
        r = self.check(b"x\tlast\\")
        self.assertTrue(r["ok"])
        self.assertIn("dangling-backslash", self.codes(r))

    def test_marker_alone_and_following_data(self):
        self.assertTrue(self.check(b"a\tb\n\\.\n")["ok"])
        r = self.check(b"a\tb\n\\.\nignored\tdata\n")
        self.assertFalse(r["ok"])
        self.assertEqual(r["records"], 1)
        self.assertEqual(r["trailing_bytes"], 13)
        self.assertIn("data-after-end-marker", self.codes(r))

    def test_marker_requires_line_ending(self):
        self.assertIn("unterminated-end-marker", self.codes(self.check(b"\\.")))

    def test_embedded_marker_is_error(self):
        for raw in [b"x\\.\ty\n", b"\\.x\ty\n"]:
            self.assertIn("end-marker-in-data", self.codes(self.check(raw)))
        self.assertIn("end-marker-in-data", self.codes(self.check(b"\\.x\ty\n", null=b"\\.x")))

    def test_escaped_marker_literal(self):
        self.assertTrue(self.check(b"\\\\.\tx\n")["ok"])

    def test_all_line_endings_and_mixed(self):
        for eol in [b"\n", b"\r", b"\r\n"]:
            self.assertTrue(self.check(eol.join([b"a\tb", b"c\td", b""]))["ok"])
        self.assertIn("mixed-line-endings", self.codes(self.check(b"a\tb\r\nc\td\n")))

    def test_final_line_without_newline(self):
        self.assertTrue(self.check(b"a\tb")["ok"])

    def test_marker_line_style(self):
        self.assertIn("mixed-line-endings", self.codes(self.check(b"a\tb\r\n\\.\n")))

    def test_bom_warns(self):
        self.assertIn("utf8-bom-is-data", self.codes(self.check(b"\xef\xbb\xbf1\tx\n")))

    def test_positions_and_no_data_echo(self):
        data = b"good\trow\nPRIVATE_MARKER\n"
        r = self.check(data)
        item = r["issues"][0]
        self.assertEqual((item["record"], item["line"], item["byte_offset"]), (2, 2, 9))
        self.assertNotIn("PRIVATE_MARKER", json.dumps(r))

    def test_issue_cap_does_not_cap_totals(self):
        r = self.check(b"bad\n" * 20, max_issues=1)
        self.assertEqual(r["error_count"], 20)
        self.assertEqual(len(r["issues"]), 1)

    def test_resource_limits_never_pass(self):
        for opts in [
            {"max_bytes": 2},
            {"max_record_bytes": 2},
            {"max_records": 1},
            {"max_seconds": 1e-12},
        ]:
            with self.subTest(opts=opts):
                r = self.check(b"a\tb\nc\td\n", **opts)
                self.assertFalse(r["complete"])
                self.assertFalse(r["ok"])
        self.assertTrue(self.check(b"a\tb\n", max_bytes=4, max_records=1)["ok"])

    def test_invalid_options(self):
        for opts in [
            {"delimiter": b"\\"},
            {"delimiter": b".."},
            {"null": b"a\tb"},
            {"null": b"\\."},
            {"max_bytes": 0},
            {"max_issues": -1},
            {"max_seconds": float("nan")},
            {"max_seconds": float("inf")},
        ]:
            with self.subTest(opts=opts), self.assertRaises(ValueError):
                self.check(b"", **opts)

    def test_io_error_is_incomplete(self):
        class Broken:
            def read(self, _):
                raise OSError("private path")

        r = audit(Broken(), 1)
        self.assertFalse(r["complete"])
        self.assertNotIn("private path", json.dumps(r))

    def test_cli_stdin_exits_and_json(self):
        base = [sys.executable, "-m", "pgcopy_lint", "-", "--columns", "2", "--format", "json"]
        for data, extra, code in [
            (b"a\tb\n", [], 0),
            (b"bad\n", [], 1),
            (b"\\p\tx\n", ["--strict"], 1),
            (b"a\tb\n", ["--max-bytes", "1"], 2),
        ]:
            p = subprocess.run(base + extra, input=data, capture_output=True, check=False)
            self.assertEqual(p.returncode, code, p.stderr + p.stdout)
            self.assertIsInstance(json.loads(p.stdout), dict)


if __name__ == "__main__":
    unittest.main()
