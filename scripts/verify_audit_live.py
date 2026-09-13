#!/usr/bin/env python3
"""Verify audited external PS1 cheat files and their production catalog metadata."""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import time
import urllib.parse
import urllib.request
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

from import_ps1_collection import parse_cheat_text

ROOT = Path(__file__).resolve().parents[1]
MAX_BYTES = 2 * 1024 * 1024
RAW_CODE_RE = re.compile(r"^[0-9A-Fa-f]{8}[\s:+-]+[0-9A-Fa-f]{1,8}$")
LABEL_RE = re.compile(r"^\s*\[([^]\r\n]+)]\s*$")
COMMENT_LABEL_RE = re.compile(r"^\s*comment\s*=\s*(.+?)\s*$", re.IGNORECASE)
META_RE = re.compile(r"^\s*(?:gametitle|author)\s*=", re.IGNORECASE)


def fetch(url: str) -> bytes:
    last_error: Exception | None = None
    for attempt in range(4):
        try:
            request = urllib.request.Request(
                url, headers={"User-Agent": "EmuCoreR-Cheat-Live-Audit"}
            )
            with urllib.request.urlopen(request, timeout=30) as response:
                return response.read()
        except Exception as error:
            last_error = error
            if attempt == 3:
                raise
            time.sleep(2**attempt)
    raise last_error  # pragma: no cover


def external_download_url(record: dict[str, object]) -> str:
    encoded_path = urllib.parse.quote(str(record["path"]), safe="/")
    return (
        f"https://raw.githubusercontent.com/{record['source']}/"
        f"{record['revision']}/{encoded_path}"
    )


def record_key(record: dict[str, object]) -> tuple[str, str, str]:
    return (str(record["source"]), str(record["revision"]), str(record["path"]))


def normalize_code_line(line: str) -> str:
    return re.sub(r"[\s:+-]+", "", line).upper()


def analyze_text(text: str) -> tuple[list[str], int]:
    """Uses the importer's parser so the live audit and the catalog agree."""
    parsed = parse_cheat_text(text)
    if parsed is None:
        raise ValueError("no supported active cheat code lines")
    blocks = list(parsed["blocks"])
    if not blocks:
        raise ValueError("no active cheat code lines")
    code_lines = [code for _, codes in blocks for code in codes]
    title_keys = {name.casefold() for name, _ in blocks}
    block_count = len(title_keys) if title_keys else len(blocks)
    return code_lines, block_count


def verify(record: dict[str, object]) -> tuple[int, int, int, frozenset[str]]:
    path = str(record["path"])
    try:
        body = fetch(external_download_url(record))
        if not 0 < len(body) <= MAX_BYTES or len(body) != record["sizeBytes"]:
            raise ValueError("size mismatch")
        if hashlib.sha256(body).hexdigest().upper() != str(record["sha256"]).upper():
            raise ValueError("SHA-256 mismatch")
        text = body.decode("utf-8-sig", errors="strict")
        if "\0" in text:
            raise ValueError("NUL byte in file")
        code_lines, block_count = analyze_text(text)
    except UnicodeDecodeError as error:
        raise ValueError(f"{path}: not strict UTF-8") from error
    except ValueError as error:
        raise ValueError(f"{path}: {error}") from error
    signature = frozenset(normalize_code_line(line) for line in code_lines)
    return len(body), len(code_lines), block_count, signature


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--batch-id", required=True)
    parser.add_argument("--workers", type=int, default=16)
    args = parser.parse_args()

    audit_path = ROOT / "audits" / f"{args.batch_id}.json"
    if not audit_path.is_file():
        raise SystemExit(f"Missing audit file: audits/{args.batch_id}.json")
    audit = json.loads(audit_path.read_text(encoding="utf-8"))
    catalog = json.loads((ROOT / "cheats.json").read_text(encoding="utf-8"))
    records = audit.get("entries", [])
    external_records = [
        record
        for record in records
        if isinstance(record, dict)
        and str(record.get("kind") or "external") == "external"
    ]
    catalog_by_download = {
        str(entry.get("downloadUrl")): entry
        for entry in catalog.get("entries", [])
        if isinstance(entry, dict)
    }

    results: dict[
        tuple[str, str, str], tuple[int, int, int, frozenset[str]]
    ] = {}
    with ThreadPoolExecutor(max_workers=args.workers) as pool:
        futures = {
            pool.submit(verify, record): record for record in external_records
        }
        for future in as_completed(futures):
            record = futures[future]
            results[record_key(record)] = future.result()

    signatures: dict[tuple[str, frozenset[str]], str] = {}
    for record in external_records:
        path = str(record["path"])
        url = external_download_url(record)
        entry = catalog_by_download.get(url)
        if entry is None:
            raise ValueError(f"{path}: catalog entry missing for {url}")
        serials = sorted(str(value).upper() for value in record.get("serials", []))
        entry_serials = sorted(
            str(value).upper() for value in (entry.get("serials") or [])
        )
        if serials != entry_serials:
            raise ValueError(f"{path}: catalog serials do not match the audit")
        crc = record.get("crc")
        if crc not in (None, "") and str(crc).upper() != str(
            entry.get("crc") or ""
        ).upper():
            raise ValueError(f"{path}: catalog crc does not match the audit")
        title_override = record.get("titleOverride")
        if title_override not in (None, "") and str(title_override) != str(
            entry.get("title")
        ):
            raise ValueError(f"{path}: catalog title does not match the audit")
        size, code_count, block_count, signature_lines = results[record_key(record)]
        if entry.get("blockCount") != block_count:
            raise ValueError(
                f"{path}: catalog blockCount does not match the file blocks"
            )
        crc_key = str(crc or "").upper() or ",".join(serials)
        signature = (crc_key, signature_lines)
        if signature in signatures:
            raise ValueError(
                f"{path}: duplicate batch cheat set matches {signatures[signature]}"
            )
        signatures[signature] = path

    generated_count = len(records) - len(external_records)
    print(
        f"LIVE_OK batch={args.batch_id} external_entries={len(results)} "
        f"generated_entries={generated_count} "
        f"distinct_signatures={len(signatures)} "
        f"bytes={sum(result[0] for result in results.values())} "
        f"code_lines={sum(result[1] for result in results.values())}"
    )


if __name__ == "__main__":
    main()
