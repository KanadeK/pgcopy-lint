"""Bounded PostgreSQL COPY text transport diagnostics, without a server."""

from __future__ import annotations

import math
import time
from typing import BinaryIO


class BudgetExceeded(Exception):
    pass


class Reader:
    def __init__(self, stream, max_bytes, deadline):
        self.stream = stream
        self.max_bytes = max_bytes
        self.deadline = deadline
        self.pending = None
        self.offset = 0
        self.line = 1
        self.previous = None

    def peek(self):
        if self.pending is None:
            self.pending = self.stream.read(1)
        return self.pending

    def read(self):
        value = self.peek()
        self.pending = None
        if not value:
            return None
        self.offset += 1
        if self.offset > self.max_bytes:
            raise BudgetExceeded("byte limit exceeded")
        if self.offset % 4096 == 0 and time.perf_counter() > self.deadline:
            raise BudgetExceeded("time budget exceeded")
        number = value[0]
        if number == 13 or (number == 10 and self.previous != 13):
            self.line += 1
        self.previous = number
        return number


def records(reader, max_record_bytes):
    """Yield raw logical records; backslash quotes the next byte including LF."""
    while True:
        data = bytearray()
        offset, line = reader.offset, reader.line
        ending = None
        while True:
            byte = reader.read()
            if byte is None:
                if data:
                    yield bytes(data), offset, line, ending
                return
            if byte == 92:
                data.append(byte)
                second = reader.read()
                if second is not None:
                    data.append(second)
            elif byte in (10, 13):
                ending = "LF" if byte == 10 else "CR"
                if byte == 13 and reader.peek() == b"\n":
                    reader.read()
                    ending = "CRLF"
                break
            else:
                data.append(byte)
            if len(data) > max_record_bytes:
                raise BudgetExceeded("logical record exceeds max_record_bytes")
        yield bytes(data), offset, line, ending


def split_fields(raw, delimiter):
    start = 0
    index = 0
    while index < len(raw):
        if raw[index] == 92:
            index += 2
        elif raw[index] == delimiter:
            yield raw[start:index], start
            index += 1
            start = index
        else:
            index += 1
    yield raw[start:], start


def unescape(raw, delimiter, on_notice=None):
    """Return decoded bytes and positional notices, never record contents."""
    output = bytearray()
    notices = []

    def notice(code, position, severity):
        if on_notice is None:
            notices.append((code, position, severity))
        else:
            on_notice(code, position, severity)

    simple = {98: 8, 102: 12, 110: 10, 114: 13, 116: 9, 118: 11}
    index = 0
    while index < len(raw):
        byte = raw[index]
        if byte != 92:
            output.append(byte)
            index += 1
            continue
        start = index
        index += 1
        if index == len(raw):
            notice("dangling-backslash", start, "warning")
            break
        byte = raw[index]
        index += 1
        if byte in simple:
            output.append(simple[byte])
        elif 48 <= byte <= 55:
            digits = bytes([byte])
            while len(digits) < 3 and index < len(raw) and 48 <= raw[index] <= 55:
                digits += bytes([raw[index]])
                index += 1
            output.append(int(digits, 8) & 255)
        elif byte == 120 and index < len(raw) and raw[index] in b"0123456789abcdefABCDEF":
            digits = raw[index : index + 1]
            index += 1
            if index < len(raw) and raw[index] in b"0123456789abcdefABCDEF":
                digits += raw[index : index + 1]
                index += 1
            output.append(int(digits, 16))
        else:
            output.append(byte)
            if byte == 46:
                notice("end-marker-in-data", start, "error")
            elif byte in (10, 13):
                notice("literal-newline-escape", start, "warning")
            elif byte not in (92, delimiter):
                notice("unknown-escape", start, "warning")
    return bytes(output), notices


def audit(
    stream: BinaryIO,
    columns: int,
    *,
    delimiter: bytes = b"\t",
    null: bytes = b"\\N",
    max_issues: int = 50,
    max_record_bytes: int = 16_777_216,
    max_bytes: int = 1_073_741_824,
    max_records: int = 10_000_000,
    max_seconds: float = 30,
) -> dict:
    """Inspect one standalone UTF-8 COPY text payload, not SQL/CSV/binary."""
    allowed = b"\t,;|:!@#$%^&*+=~?/-_()[]{}<>\"'` "
    if columns < 1 or columns > 1600:
        raise ValueError("columns must be between 1 and 1600")
    if len(delimiter) != 1 or delimiter[0] not in allowed:
        raise ValueError("delimiter must be tab or supported ASCII punctuation (not dot/backslash)")
    if any(byte in null for byte in (b"\r", b"\n", b"\0", delimiter)) or null == b"\\.":
        raise ValueError("null marker contains a delimiter, control byte or end marker")
    null.decode("utf-8")
    if max_issues < 0 or min(max_record_bytes, max_bytes, max_records) < 1:
        raise ValueError("resource limits must be positive; max_issues may be zero")
    if not math.isfinite(max_seconds) or max_seconds <= 0:
        raise ValueError("max_seconds must be positive and finite")
    result = {
        "schema_version": 1,
        "scope": "utf8-copy-text-transport",
        "columns": columns,
        "records": 0,
        "fields": 0,
        "null_fields": 0,
        "error_count": 0,
        "warning_count": 0,
        "issues": [],
        "end_marker": False,
        "trailing_bytes": 0,
        "complete": False,
        "ok": False,
    }

    def issue(code, offset, line, record, field=None, severity="error"):
        result[severity + "_count"] += 1
        if len(result["issues"]) < max_issues:
            result["issues"].append(
                {
                    "code": code,
                    "severity": severity,
                    "byte_offset": offset,
                    "line": line,
                    "record": record,
                    "field": field,
                }
            )

    reader = Reader(stream, max_bytes, time.perf_counter() + max_seconds)
    style = None
    try:
        for raw, offset, line, ending in records(reader, max_record_bytes):
            if time.perf_counter() > reader.deadline:
                raise BudgetExceeded("time budget exceeded")
            record = result["records"] + 1
            if ending:
                if style and style != ending:
                    issue("mixed-line-endings", offset + len(raw), line, record)
                style = style or ending
            if raw == b"\\.":
                result["end_marker"] = True
                if not ending:
                    issue("unterminated-end-marker", offset, line, record)
                first = reader.offset
                while reader.read() is not None:
                    result["trailing_bytes"] += 1
                if result["trailing_bytes"]:
                    issue("data-after-end-marker", first, line + 1, record)
                break
            if result["records"] >= max_records:
                raise BudgetExceeded("record limit exceeded")
            result["records"] += 1
            if offset == 0 and raw.startswith(b"\xef\xbb\xbf"):
                issue("utf8-bom-is-data", 0, line, record, 1, "warning")
            try:
                raw.decode("utf-8")
            except UnicodeDecodeError as exc:
                issue("invalid-input-utf8", offset + exc.start, line, record)
            if b"\0" in raw:
                issue("nul-in-input", offset + raw.index(0), line, record)
            count = 0
            for count, (field, start) in enumerate(split_fields(raw, delimiter[0]), 1):
                result["fields"] += 1

                def emit(
                    code,
                    position,
                    severity,
                    start=start,
                    count=count,
                    is_null=field == null,
                    offset=offset,
                    line=line,
                    record=record,
                ):
                    if not is_null or code == "end-marker-in-data":
                        issue(code, offset + start + position, line, record, count, severity)

                decoded, _ = unescape(field, delimiter[0], on_notice=emit)
                if field == null:
                    result["null_fields"] += 1
                    continue
                if b"\0" in decoded:
                    issue("nul-after-unescape", offset + start, line, record, count)
                try:
                    decoded.decode("utf-8")
                except UnicodeDecodeError:
                    issue("invalid-decoded-utf8", offset + start, line, record, count)
            if count != columns:
                issue("field-count", offset, line, record)
        result["complete"] = True
    except BudgetExceeded as exc:
        result["error"] = str(exc)
    except OSError:
        result["error"] = "input read failed"
    result["bytes_examined"] = reader.offset
    result["line_ending"] = style
    result["ok"] = result["complete"] and result["error_count"] == 0
    return result
