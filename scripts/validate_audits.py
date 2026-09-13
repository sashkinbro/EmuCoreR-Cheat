#!/usr/bin/env python3
from __future__ import annotations

import hashlib
import json
import re
import urllib.parse
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
CATALOG_REPOSITORY = "sashkinbro/EmuCoreR-Cheat"
MIRROR_RAW_PREFIX = f"https://raw.githubusercontent.com/{CATALOG_REPOSITORY}/main/"
EXTERNAL_RAW_ROOT = "https://raw.githubusercontent.com/"
CRC_RE = re.compile(r"^[0-9A-Fa-f]{8}$")
SHA256_RE = re.compile(r"^[0-9A-Fa-f]{64}$")
REVISION_RE = re.compile(r"^[0-9a-f]{40}$")
SERIAL_RE = re.compile(r"^[A-Z]{4}-[0-9]{5}$")
SOURCE_RE = re.compile(r"^[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+$")
AUDIT_SUFFIXES = {".txt", ".cht", ".pnach"}
MAX_CHEAT_BYTES = 2 * 1024 * 1024


def normalized_serials(values: object) -> list[str]:
    if not isinstance(values, list):
        return []
    return sorted(str(value).strip().upper() for value in values)


def unsafe_path(path: str) -> bool:
    if not path or path.startswith(("/", "\\")):
        return True
    if re.match(r"^[A-Za-z]:", path):
        return True
    return ".." in Path(path).parts


def main() -> None:
    catalog = json.loads((ROOT / "cheats.json").read_text(encoding="utf-8"))
    entries = catalog.get("entries", [])
    if not isinstance(entries, list):
        entries = []
    by_download = {
        str(entry.get("downloadUrl")): entry
        for entry in entries
        if isinstance(entry, dict)
    }
    errors: list[str] = []
    seen_batches: set[str] = set()
    seen_sources: set[tuple[str, str, str]] = set()
    seen_hashes: set[str] = set()
    audit_files = sorted((ROOT / "audits").glob("batch-*.json"))
    entry_total = 0
    for audit_file in audit_files:
        audit = json.loads(audit_file.read_text(encoding="utf-8"))
        batch_id = audit.get("batchId")
        if not isinstance(batch_id, str) or not batch_id.strip():
            errors.append(f"{audit_file.name}: batchId is required")
        elif batch_id in seen_batches:
            errors.append(f"{audit_file.name}: duplicate batchId {batch_id}")
        if isinstance(batch_id, str):
            seen_batches.add(batch_id)
        records = audit.get("entries")
        if not isinstance(records, list) or not records:
            errors.append(f"{audit_file.name}: entries must be a non-empty array")
            continue
        for index, record in enumerate(records):
            label = f"{audit_file.name}.entries[{index}]"
            if not isinstance(record, dict):
                errors.append(f"{label} must be an object")
                continue
            entry_total += 1
            source = str(record.get("source", ""))
            revision = str(record.get("revision", ""))
            path = str(record.get("path", ""))
            kind = str(record.get("kind") or "external")
            sha256 = str(record.get("sha256", "")).upper()
            size_bytes = record.get("sizeBytes")
            crc = str(record.get("crc", ""))
            serials = record.get("serials")
            source_key = (source, revision, path)
            if source_key in seen_sources:
                errors.append(
                    f"{label}: duplicate (source, revision, path) record"
                )
            seen_sources.add(source_key)
            if not SOURCE_RE.fullmatch(source):
                errors.append(f"{label}: source must use the owner/repo form")
            if not REVISION_RE.fullmatch(revision):
                errors.append(
                    f"{label}: revision must be a 40-character lowercase Git SHA"
                )
            if kind not in {"external", "generated"}:
                errors.append(f"{label}: kind must be external or generated")
            if unsafe_path(path) or Path(path).suffix.lower() not in AUDIT_SUFFIXES:
                errors.append(
                    f"{label}: path must be a relative .txt, .cht or legacy .pnach "
                    f"cheat file"
                )
            if not SHA256_RE.fullmatch(sha256):
                errors.append(f"{label}: sha256 must be 64 hex characters")
            elif sha256 in seen_hashes:
                errors.append(f"{label}: duplicate cheat content hash")
            seen_hashes.add(sha256)
            if not isinstance(size_bytes, int) or isinstance(size_bytes, bool) or not (
                0 < size_bytes <= MAX_CHEAT_BYTES
            ):
                errors.append(f"{label}: sizeBytes must be between 1 and 2 MiB")
            if kind == "generated" and not unsafe_path(path):
                mirror = ROOT / path
                if not mirror.is_file():
                    errors.append(f"{label}: mirrored cheat file {path} is missing")
                else:
                    body = mirror.read_bytes()
                    if len(body) != size_bytes:
                        errors.append(f"{label}: mirror size does not match sizeBytes")
                    if hashlib.sha256(body).hexdigest().upper() != sha256.upper():
                        errors.append(f"{label}: mirror SHA-256 does not match sha256")
            if crc and not CRC_RE.fullmatch(crc):
                errors.append(f"{label}: crc must be eight hex characters")
            if not isinstance(serials, list) or any(
                not SERIAL_RE.fullmatch(str(value)) for value in serials
            ):
                errors.append(f"{label}: serials must be a list of PS1 serials")
            encoded_path = urllib.parse.quote(path, safe="/")
            if kind == "generated":
                download_url = MIRROR_RAW_PREFIX + encoded_path
            else:
                download_url = (
                    f"{EXTERNAL_RAW_ROOT}{source}/{revision}/{encoded_path}"
                )
            entry = by_download.get(download_url)
            if entry is None:
                errors.append(
                    f"{label}: no catalog entry with downloadUrl {download_url}"
                )
                continue
            record_serials = normalized_serials(serials)
            if record_serials and record_serials != normalized_serials(
                entry.get("serials")
            ):
                errors.append(
                    f"{label}: catalog serials do not match the audit record"
                )
            if crc and crc.upper() != str(entry.get("crc") or "").upper():
                errors.append(f"{label}: catalog crc does not match the audit record")
            title_override = record.get("titleOverride")
            if title_override not in (None, "") and str(title_override) != str(
                entry.get("title")
            ):
                errors.append(f"{label}: catalog title does not match titleOverride")
    if errors:
        raise SystemExit("\n".join(errors))
    print(f"Audit valid: {len(audit_files)} batches, {entry_total} entries")


if __name__ == "__main__":
    main()
