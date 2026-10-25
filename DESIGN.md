# Design and review

Read binary input, retain one bounded logical record, locate unescaped separators,
compare raw NULL markers, then decode escapes and validate UTF-8. Numeric escapes
are bytes rather than Unicode code points. Two escaped UTF-8 bytes can therefore
form one valid character. A NULL marker bypasses value decoding errors, but cannot
bypass an embedded end marker because the server recognizes that earlier.

Diagnostics retain no input values. The sample cap affects storage only; all
error totals continue. Byte/record/time limits explicitly produce incomplete
reports. A literal escaped newline is parsed but warned about. The server's
acceptance of unknown escapes is preserved, with optional warning failure.

Review consulted the PostgreSQL 18 COPY specification and
[upstream parser](https://github.com/postgres/postgres/blob/REL_18_STABLE/src/backend/commands/copyfromparse.c)
to resolve ambiguity around embedded end markers and octal overflow. This is an
independent Python implementation; no source was copied. Differential tests use
synthetic inputs and PostgreSQL itself as the reference. The tool is intentionally
stricter about bytes following an end marker because ignored suffixes cause
incomplete imports. It does not claim a complete model of arbitrary COPY options.

One-byte reads use the caller's buffered stream. Processing cost is linear in
input size, with Python-level parsing overhead. Counts for partial scans cover
only visited records; the final over-budget record may be partly consumed. Reading
one byte ahead is necessary for CRLF and EOF recognition.
