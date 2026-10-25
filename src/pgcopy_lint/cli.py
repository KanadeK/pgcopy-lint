import argparse
import json
import sys
from contextlib import nullcontext

from . import __version__
from .core import audit


def main(argv=None):
    parser = argparse.ArgumentParser(
        description="Lint a standalone UTF-8 PostgreSQL COPY text payload."
    )
    parser.add_argument("file", help="input file, or - for binary stdin")
    parser.add_argument("--columns", required=True, type=int)
    parser.add_argument("--delimiter", default="\t", help="one ASCII character; default tab")
    parser.add_argument("--null", default="\\N", help="raw null marker; default backslash-N")
    parser.add_argument("--format", choices=["text", "json"], default="text")
    parser.add_argument("--strict", action="store_true", help="warnings also fail the gate")
    parser.add_argument("--max-issues", type=int, default=50)
    parser.add_argument("--max-record-bytes", type=int, default=16_777_216)
    parser.add_argument("--max-bytes", type=int, default=1_073_741_824)
    parser.add_argument("--max-records", type=int, default=10_000_000)
    parser.add_argument("--max-seconds", type=float, default=30)
    parser.add_argument("--version", action="version", version=__version__)
    args = parser.parse_args(argv)
    try:
        context = nullcontext(sys.stdin.buffer) if args.file == "-" else open(args.file, "rb")
        with context as stream:
            result = audit(
                stream,
                args.columns,
                delimiter=args.delimiter.encode("ascii"),
                null=args.null.encode("utf-8"),
                max_issues=args.max_issues,
                max_record_bytes=args.max_record_bytes,
                max_bytes=args.max_bytes,
                max_records=args.max_records,
                max_seconds=args.max_seconds,
            )
    except (OSError, ValueError) as exc:
        result = {"schema_version": 1, "ok": False, "complete": False, "error": str(exc)}
    except KeyboardInterrupt:
        return 130
    result["strict"] = args.strict
    if args.strict and result.get("warning_count", 0):
        result["ok"] = False
    if args.format == "json":
        print(json.dumps(result, indent=2, ensure_ascii=True))
    else:
        print(
            f"records={result.get('records', 0)} errors={result.get('error_count', 0)} "
            f"warnings={result.get('warning_count', 0)} complete={result['complete']} "
            f"ok={result['ok']}"
        )
        for item in result.get("issues", []):
            print(json.dumps(item))
        if "error" in result:
            print(result["error"], file=sys.stderr)
    return 2 if not result["complete"] else (0 if result["ok"] else 1)
