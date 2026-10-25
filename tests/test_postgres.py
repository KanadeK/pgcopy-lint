"""Optional differential tests against an actual UTF-8 PostgreSQL server."""

import io
import os
import unittest

from pgcopy_lint.core import audit


@unittest.skipUnless(os.environ.get("PGCOPY_TEST_DSN"), "set PGCOPY_TEST_DSN for server tests")
class PostgresTests(unittest.TestCase):
    def setUp(self):
        import psycopg

        self.psycopg = psycopg
        self.db = psycopg.connect(os.environ["PGCOPY_TEST_DSN"], autocommit=True)
        self.addCleanup(self.db.close)
        self.db.execute("SET client_encoding = 'UTF8'")
        self.db.execute("CREATE TEMP TABLE copy_probe(a text, b text)")

    def accepted(self, data, options=""):
        self.db.execute("TRUNCATE copy_probe")
        try:
            with self.db.cursor().copy("COPY copy_probe FROM STDIN " + options) as copy:
                copy.write(data)
        except self.psycopg.Error:
            return False
        return True

    def test_acceptance_corpus(self):
        cases = [
            b"a\tb\n",
            b"a\tb",
            b"\t\n",
            b"",
            b"\\N\t\\\\N\n",
            b"\\xC3\\xA9\tx\n",
            b"\\303\\251\tx\n",
            b"\\p\tx\n",
            b"a\\\nb\tx\n",
            b"a\\\tb\tx\n",
            b"a\\\\\tb\n",
            b"a\tb\r\nc\td\r\n",
            b"a\tb\rc\td\r",
            b"one\n",
            b"a\tb\tc\n",
            b"\\0\tx\n",
            b"\\xff\tx\n",
            b"\xff\tx\n",
            b"a\tb\r\nc\td\n",
            b"\\.x\ty\n",
            b"x\\.\ty\n",
            b"\\\\.\tx\n",
            b"x\ty\\",
            b"a\tb\n\\.\n",
        ]
        for data in cases:
            with self.subTest(data=data):
                self.assertEqual(audit(io.BytesIO(data), 2)["ok"], self.accepted(data))

    def test_raw_null_precedence(self):
        data = b"\\000\tx\n"
        self.assertTrue(audit(io.BytesIO(data), 2, null=b"\\000")["ok"])
        self.assertTrue(self.accepted(data, "WITH (NULL E'\\\\000')"))
        self.assertEqual(self.db.execute("SELECT a, b FROM copy_probe").fetchone(), (None, "x"))

    def test_custom_delimiter_and_decoded_values(self):
        data = b"a\\|b|\\xC3\\xA9\n"
        self.assertTrue(audit(io.BytesIO(data), 2, delimiter=b"|")["ok"])
        self.assertTrue(self.accepted(data, "WITH (DELIMITER '|')"))
        self.assertEqual(self.db.execute("SELECT a, b FROM copy_probe").fetchone(), ("a|b", "é"))

    def test_trailing_data_is_stricter_than_server(self):
        data = b"a\tb\n\\.\nignored\tdata\n"
        self.assertTrue(self.accepted(data))
        self.assertEqual(self.db.execute("SELECT count(*) FROM copy_probe").fetchone()[0], 1)
        self.assertFalse(audit(io.BytesIO(data), 2)["ok"])


if __name__ == "__main__":
    unittest.main()
