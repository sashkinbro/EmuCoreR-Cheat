#!/usr/bin/env python3
from __future__ import annotations

import json
import re
from pathlib import Path
from urllib.parse import unquote, urlparse

ROOT = Path(__file__).resolve().parents[1]
CRC_RE = re.compile(r"^[0-9A-F]{8}$")
SERIAL_RE = re.compile(r"^[A-Z]{4}-[0-9]{5}$")
MIRROR_RAW_PREFIX = (
    "https://raw.githubusercontent.com/sashkinbro/EmuCoreR-Cheat/main/"
)
MIRROR_SUFFIXES = {".txt", ".cht"}


def valid_https(value: object) -> bool:
    parsed = urlparse(str(value))
    return parsed.scheme == "https" and bool(parsed.netloc)


def main() -> None:
    data = json.loads((ROOT / "cheats.json").read_text(encoding="utf-8"))
    errors: list[str] = []
    if data.get("schemaVersion") != 1:
        errors.append("schemaVersion must be 1")
    entries = data.get("entries")
    if not isinstance(entries, list):
        errors.append("entries must be an array")
        entries = []
    ids: set[str] = set()
    downloads: set[str] = set()
    for index, entry in enumerate(entries):
        label = f"entries[{index}]"
        if not isinstance(entry, dict):
            errors.append(f"{label} must be an object")
            continue
        entry_id = entry.get("id")
        if not isinstance(entry_id, str) or not entry_id.strip():
            errors.append(f"{label}.id must not be empty")
        elif entry_id in ids:
            errors.append(f"duplicate id: {entry_id}")
        if isinstance(entry_id, str):
            ids.add(entry_id)
        crc = entry.get("crc")
        if crc not in (None, ""):
            if not CRC_RE.fullmatch(str(crc)):
                errors.append(
                    f"{label}.crc must be eight uppercase hex characters when present"
                )
        serials = entry.get("serials")
        if serials is not None:
            if not isinstance(serials, list):
                errors.append(f"{label}.serials must be an array when present")
            else:
                for serial in serials:
                    if not SERIAL_RE.fullmatch(str(serial)):
                        errors.append(
                            f"{label}.serials contains invalid PS1 serial {serial}"
                        )
        for field in ("downloadUrl", "sourceUrl"):
            if not valid_https(entry.get(field)):
                errors.append(f"{label}.{field} must be an HTTPS URL")
        authors = entry.get("authors")
        if (
            not isinstance(authors, list)
            or not authors
            or any(not str(author).strip() for author in authors)
        ):
            errors.append(f"{label}.authors must be a non-empty array of names")
        block_count = entry.get("blockCount")
        if (
            not isinstance(block_count, int)
            or isinstance(block_count, bool)
            or block_count < 1
        ):
            errors.append(f"{label}.blockCount must be a positive integer")
        download_url = str(entry.get("downloadUrl", ""))
        if download_url in downloads:
            errors.append(f"duplicate download URL: {download_url}")
        downloads.add(download_url)
        if not download_url.startswith(MIRROR_RAW_PREFIX):
            continue
        relative_text = unquote(download_url.removeprefix(MIRROR_RAW_PREFIX))
        local_file = (ROOT / relative_text).resolve()
        try:
            local_file.relative_to(ROOT.resolve())
        except ValueError:
            errors.append(f"{label}.downloadUrl escapes the repository")
            continue
        if local_file.suffix.lower() not in MIRROR_SUFFIXES:
            errors.append(
                f"{label}.downloadUrl must point to a mirrored .txt or .cht cheat "
                f"file, not a PNACH"
            )
        elif not local_file.is_file():
            errors.append(
                f"{label}.downloadUrl has no mirrored cheat file: {relative_text}"
            )
    if errors:
        raise SystemExit("\n".join(errors))
    print(f"Catalog valid: {len(entries)} entries")


if __name__ == "__main__":
    main()
