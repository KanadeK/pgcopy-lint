# pgcopy-lint

Inspect a PostgreSQL **COPY text data file** before sending it to a database.
Find column-count errors, invalid UTF-8, NUL bytes hidden in escapes, mixed line
endings and data that PostgreSQL would ignore after an end marker. Reports contain
positions and counts, never field values. No server or runtime dependency is needed.

This is a transport linter, not a restore verifier. It accepts one standalone
payload in COPY **text** format, with UTF-8 input and UTF-8 destination encoding.
It does not parse SQL dumps, CSV, binary COPY, column types or database constraints.
Always complete a real restore/import test for the destination schema.

## Install and reproduce

Requires Python 3.11+. Clone this repository and run:

```sh
python -m venv .venv
# POSIX: source .venv/bin/activate
# PowerShell: .venv\Scripts\Activate.ps1
python -m pip install .
pgcopy-lint examples/good.copy --columns 3
pgcopy-lint examples/bad.copy --columns 3 --format json
```

The first exits 0. The second exits 1 and reports excess fields, a decoded NUL,
and ignored data after `\.`. Fixtures contain only synthetic records.
No files are created by the linter. Uninstall with `python -m pip uninstall pgcopy-lint`.
You can then remove your virtual environment. `python -m pgcopy_lint` is equivalent.
Release wheels/source archives include SHA256SUMS; install a wheel with
`python -m pip install path/to/file.whl`. This project is not published to PyPI.

Create a compatible source using PostgreSQL, for example in psql:

```sql
\copy (SELECT id, name, note FROM items) TO 'items.copy' WITH (FORMAT text, ENCODING 'UTF8')
```

Then run `pgcopy-lint items.copy --columns 3`. Supply the exact column count and
delimiter/null settings used by your COPY command. Headers and DEFAULT markers
are unsupported. The default delimiter is a literal tab and the NULL marker is `\N`.
For a pipe-delimited payload: `pgcopy-lint items.copy --columns 3 --delimiter '|'`.

## What is diagnosed

- Too many or too few fields in each logical record; escaped delimiters are data.
- Invalid UTF-8 in raw input or bytes reconstructed from octal/hex escapes.
- Raw or decoded NUL bytes, which PostgreSQL text values cannot contain.
- Inconsistent LF, CRLF or CR record endings.
- Unescaped `\.` embedded inside a record, an unterminated marker, and any bytes
  following a whole-record end marker. Ignored trailing data is deliberately an
  error even when the server accepts the prefix.
- Warnings for unknown escapes (PostgreSQL drops their backslash), a dangling
  final backslash, literal escaped line breaks, or an initial BOM treated as data.

`--strict` makes warnings fail the gate. Unknown escapes are **not** syntax errors;
without strict mode, a file containing only warnings exits 0. NULL comparison uses
the raw field before decoding. Octal escapes use up to three digits, hex escapes
up to two. UTF-8 characters may be built from multiple escaped bytes. Line numbers
are physical; record and field numbers are 1-based, byte offsets are 0-based.
For multi-line records, an issue's line is the starting physical line of the record.

JSON `schema_version: 1` includes `complete`, `ok`, record/field/null counts,
error/warning counts, at most `--max-issues` diagnostics, newline style, inspected
bytes and marker/trailing-byte information. Totals continue after the issue cap.

Exit **0**: complete with no failing diagnostics. **1**: complete with errors (or
strict warnings). **2**: bad options, I/O failure or incomplete resource-limited
scan. **130**: interrupted. Empty input is a valid zero-record payload; that says
nothing about whether an export unexpectedly lost all records.

## Resource controls

```sh
pgcopy-lint items.copy --columns 3 --max-record-bytes 1048576 --max-bytes 500000000
pgcopy-lint items.copy --columns 3 --max-records 1000000 --max-seconds 60 --max-issues 20
```

Defaults: 16 MiB per logical record, 1 GiB examined input, 10 million records,
30 seconds, 50 retained diagnostics. Memory is bounded by the current record and
bounded diagnostics. Input is read incrementally and never rewritten. Limits
are cooperative; a blocked file/pipe read can exceed the time budget. Use OS
process limits for hostile inputs. `-` reads binary stdin; avoid shells that
re-encode byte streams. Delimiters are restricted to tab, space and common ASCII
punctuation (excluding dot/backslash); other encodings and delimiters are outside
this version's supported profile. Compressed input must be decompressed first.

## Verification and alternatives

Unit tests cover boundary cases, byte positions, redaction, limits, exit codes and
escaping. Optional tests send the same corpus through actual PostgreSQL COPY,
and CI runs these against PostgreSQL 16 and 18:

```sh
python -m pip install . 'psycopg[binary]==3.3.6'
# Set PGCOPY_TEST_DSN to your disposable local test database.
python -m unittest discover -s tests -v
```

Only temporary tables are used. The default unit run skips server tests when the
variable is absent. See VALIDATION.json and Actions for actual executed evidence.
[COPY documentation](https://www.postgresql.org/docs/18/sql-copy.html) is the format
reference. Server-side COPY remains definitive for type and constraint validation;
pgloader is a migration/loader alternative, and CSV linters implement a different
escaping grammar. [Immich's restore issue](https://github.com/immich-app/immich/issues/27761)
is one example of why early file-level diagnostics are useful, not proof that this
tool can repair that database.

## 中文说明

离线检查 PostgreSQL COPY text 数据载荷：列数、转义后的 UTF-8/NUL、换行风格，
以及 `\.` 提前结束后被忽略的数据。默认不输出字段值。只支持独立 UTF-8 text
载荷，不支持整个 SQL dump、CSV、二进制格式，也不验证列类型或数据库约束。
资源限制导致未检查完时退出 2，不会误报通过。实际导入和恢复测试仍然必要。
