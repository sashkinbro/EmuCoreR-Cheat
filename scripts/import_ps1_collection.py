#!/usr/bin/env python3
"""Deterministic importer for the EmuCoreR PlayStation 1 cheat catalog.

Sources are pinned Git repositories. Files are downloaded from codeload at the
exact revision, parsed as raw GameShark/CodeBreaker text (plain text, libretro
``cheatN_desc``/``cheatN_code`` or DuckStation ``[Block]`` INI), deduplicated by
their normalized active code lines and written to ``cheats.json`` together with
an immutable audit batch (source, revision, path, size, SHA-256, serials).

Mirrors are only written when ``mirrorFiles`` is true; otherwise the catalog
uses the immutable upstream raw URL. Every entry keeps the original author
credit, source name, source URL and license so attribution survives.
"""

from __future__ import annotations

import hashlib
import io
import json
import os
import re
import urllib.parse
import urllib.request
import zipfile
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
CATALOG_REPOSITORY = "sashkinbro/EmuCoreR-Cheat"
MIRROR_RAW_PREFIX = (
    f"https://raw.githubusercontent.com/{CATALOG_REPOSITORY}/main/files/"
)
MAX_FILE_BYTES = 2 * 1024 * 1024
CHEAT_SUFFIXES = {".txt", ".cht"}
AUDIT_BATCH_ID = "batch-001"

RAW_CODE_RE = re.compile(r"^[0-9A-Fa-f]{8}[\s:+-]+[0-9A-Fa-f]{1,8}$")
PLACEHOLDER_RE = re.compile(r"^[0-9A-Fa-f]{8}[\s:+-]+\?+$")
REVISION_RE = re.compile(r"^[0-9a-f]{40}$")
CRC_RE = re.compile(r"^[0-9A-F]{8}$")
SERIAL_RE = re.compile(r"\b([A-Za-z]{4})[-_. ]?(\d{2,3})[-_. ]?(\d{2,3})\b")
SERIAL_NAME_RE = re.compile(r"([A-Za-z]{4})[-_. ]?(\d{5})")
FILE_SERIAL_RE = re.compile(r"^(?:.*_)?([A-Za-z]{4})-?(\d{5})(?:_.*)?$")

LABEL_RE = re.compile(r"^\s*\[([^]\r\n]+)]\s*$")
COMMENT_LABEL_RE = re.compile(r"^\s*comment\s*=\s*(.+?)\s*$", re.IGNORECASE)
AUTHOR_RE = re.compile(r"^\s*author\s*=\s*(.+?)\s*$", re.IGNORECASE)
GAMETITLE_RE = re.compile(r"^\s*gametitle\s*=\s*(.+?)\s*$", re.IGNORECASE)
METADATA_RE = re.compile(r"^[A-Za-z][A-Za-z0-9 _]*\s*=.*$")
LIBRETRO_DESC_RE = re.compile(r"^cheat(\d+)_desc\s*=\s*\"?(.*?)\"?\s*$", re.IGNORECASE)
LIBRETRO_CODE_RE = re.compile(r"^cheat(\d+)_code\s*=\s*\"?(.+?)\"?\s*$", re.IGNORECASE)
CHTDB_HEADER_RE = re.compile(r";\s*\[\s*(.*?)\s*\{([A-Za-z]{4}-?\d{5})\}\s*]")

# The PlayStation titles index mirrors the app's bundled serial -> title map.
TITLES_INDEX_PATH = ROOT / "scripts" / "ps1_titles.json"

# The app matches packs by serial, so every imported file must resolve to the
# exact regional serials. Titles without a reliable index match are listed here.
SERIAL_OVERRIDES: dict[str, list[str]] = {
    "bugs bunny taz time busters": ["SLUS-01144"],
    "crash bandicoot": ["SCUS-94900"],
    "doom": ["SLUS-00077"],
    "gran turismo": ["SCUS-94194"],
    "gran turismo 2": ["SCUS-94488", "SCUS-94455"],
    "grand theft auto": ["SLUS-00106"],
    "medal of honor": ["SLUS-00974"],
    "mortal kombat trilogy": ["SLUS-00330"],
    "nascar rumble": ["SLUS-01068"],
    "nickelodeon spongebob squarepants supersponge": ["SLUS-01352"],
    "silent hill": ["SLUS-00707"],
    "spyro year of the dragon": ["SCUS-94467"],
    "tekken 3": ["SLUS-00402"],
}

REGION_PRIORITY = ("SCUS", "SLUS", "SCES", "SLES", "SCPS", "SLPS", "SLPM", "SCED")

SOURCES: list[dict[str, object]] = [
    {
        "id": "libretro-ps1",
        "repository": "libretro/libretro-database",
        "revision": "ff28a5e5bca21f7ae2001602d2e0585cf66c9b5c",
        "sourceName": "libretro PlayStation 1 Cheats",
        "license": "CC-BY-SA-4.0",
        "fallbackAuthor": "libretro-database contributors",
        "paths": ["cht/Sony - PlayStation/"],
        "mirrorFiles": True,
        "include": [
            "cht/Sony - PlayStation/Bugs Bunny _ Taz - Time Busters (USA, Europe) (GameShark).cht",
            "cht/Sony - PlayStation/Crash Bandicoot (World) (GameShark).cht",
            "cht/Sony - PlayStation/Crash Bandicoot (World) (Game Buster).cht",
            "cht/Sony - PlayStation/Doom (World) (GameShark).cht",
            "cht/Sony - PlayStation/Doom (World) (Game Buster).cht",
            "cht/Sony - PlayStation/Gran Turismo (USA) (GameShark).cht",
            "cht/Sony - PlayStation/Gran Turismo (USA) (DuckStation).cht",
            "cht/Sony - PlayStation/Gran Turismo 2 (USA) (DuckStation).cht",
            "cht/Sony - PlayStation/Grand Theft Auto (USA, Europe) (GameShark).cht",
            "cht/Sony - PlayStation/Grand Theft Auto (USA, Europe) (Game Buster).cht",
            "cht/Sony - PlayStation/Medal of Honor (USA, Europe) (GameShark).cht",
            "cht/Sony - PlayStation/Medal of Honor (USA, Europe) (Game Buster).cht",
            "cht/Sony - PlayStation/Mortal Kombat Trilogy (World) (GameShark).cht",
            "cht/Sony - PlayStation/Mortal Kombat Trilogy (World) (Game Buster).cht",
            "cht/Sony - PlayStation/NASCAR Rumble (USA) (GameShark).cht",
            "cht/Sony - PlayStation/Nickelodeon SpongeBob SquarePants - SuperSponge (USA, Europe) (GameShark).cht",
            "cht/Sony - PlayStation/Silent Hill (World) (GameShark).cht",
            "cht/Sony - PlayStation/Silent Hill (World) (Game Buster).cht",
            "cht/Sony - PlayStation/Spyro - Year of the Dragon (USA, Europe) (GameShark).cht",
            "cht/Sony - PlayStation/Spyro - Year of the Dragon (USA, Europe) (Game Buster).cht",
            "cht/Sony - PlayStation/Tekken 3 (World) (GameShark).cht",
        ],
    },
    {
        "id": "cookieplmonster-ps1",
        "repository": "CookiePLMonster/Console-Cheat-Codes",
        "revision": "f55aa8db8e6c79a2af6a9dd216b46635fc7324b5",
        "sourceName": "CookiePLMonster Console Cheat Codes",
        "license": "MIT",
        "fallbackAuthor": "CookiePLMonster and the credited code authors",
        "paths": ["PS1/Gran Turismo/", "PS1/Gran Turismo 2/"],
        "mirrorFiles": True,
        "include": [
            "PS1/Gran Turismo/60 FPS/NTSC-U 1.0.cht",
            "PS1/Gran Turismo/60 FPS/NTSC-U 1.1.cht",
            "PS1/Gran Turismo/Sim timescale in Arcade/NTSC-U 1.1.cht",
            "PS1/Gran Turismo 2/16x9 Widescreen/NTSC-U 1.1.cht",
            "PS1/Gran Turismo 2/16x9 Widescreen/NTSC-U 1.2.cht",
            "PS1/Gran Turismo 2/21x9 Widescreen/NTSC-U 1.1.cht",
            "PS1/Gran Turismo 2/21x9 Widescreen/NTSC-U 1.2.cht",
            "PS1/Gran Turismo 2/60 FPS/NTSC-U 1.1.cht",
            "PS1/Gran Turismo 2/60 FPS/NTSC-U 1.2.cht",
            "PS1/Gran Turismo 2/8MB RAM/NTSC-U 1.1, NTSC-U 1.2.cht",
            "PS1/Gran Turismo 2/BGM switch/NTSC-U 1.1.cht",
            "PS1/Gran Turismo 2/BGM switch/NTSC-U 1.2.cht",
            "PS1/Gran Turismo 2/Fixed event generator/NTSC-U 1.1.cht",
            "PS1/Gran Turismo 2/Fixed event generator/NTSC-U 1.2.cht",
            "PS1/Gran Turismo 2/Full detail AI cars/NTSC-U 1.1, NTSC-U 1.2.cht",
            "PS1/Gran Turismo 2/HUD toggle/NTSC-U 1.1.cht",
            "PS1/Gran Turismo 2/HUD toggle/NTSC-U 1.2.cht",
            "PS1/Gran Turismo 2/Higher draw distance/NTSC-U 1.1.cht",
            "PS1/Gran Turismo 2/Higher draw distance/NTSC-U 1.2.cht",
            "PS1/Gran Turismo 2/Metric units/NTSC-U 1.1.cht",
            "PS1/Gran Turismo 2/Metric units/NTSC-U 1.2.cht",
            "PS1/Gran Turismo 2/Replay cameras/NTSC-U 1.1, NTSC-U 1.2.cht",
            "PS1/Gran Turismo 2/True Endurance/NTSC-U 1.1.cht",
            "PS1/Gran Turismo 2/True Endurance/NTSC-U 1.2.cht",
        ],
    },
    {
        "id": "chtdb",
        "repository": "duckstation/chtdb",
        "revision": "aa70de735d791639a210faa52ee974de61a10347",
        "sourceName": "DuckStation Community Cheat Database",
        "license": "See upstream source terms",
        "fallbackAuthor": "DuckStation CHTDB contributors / original code authors",
        "paths": ["cheats/"],
        "mirrorFiles": False,
        "include": [
            "cheats/SCUS-94900.cht",
            "cheats/SLUS-00077.cht",
            "cheats/SCUS-94194.cht",
            "cheats/SCUS-94488.cht",
            "cheats/SCUS-94455.cht",
            "cheats/SLUS-00106.cht",
            "cheats/SLUS-00974.cht",
            "cheats/SLUS-00330.cht",
            "cheats/SLUS-01068.cht",
            "cheats/SLUS-01352.cht",
            "cheats/SLUS-00707.cht",
            "cheats/SCUS-94467.cht",
            "cheats/SLUS-00402.cht",
            "cheats/SLUS-01144.cht",
        ],
    },
]


def fetch(url: str) -> bytes:
    request = urllib.request.Request(url, headers={"User-Agent": "EmuCoreR-Catalog-Builder"})
    with urllib.request.urlopen(request, timeout=120) as response:
        return response.read()


def unique_titles(values: list[str]) -> list[str]:
    seen: set[str] = set()
    result: list[str] = []
    for value in values:
        cleaned = " ".join(value.split())
        key = cleaned.casefold()
        if cleaned and key not in seen:
            seen.add(key)
            result.append(cleaned)
    return result


def normalize_serial(value: object) -> str | None:
    compact = re.sub(r"[-_ .]", "", str(value).upper())
    if not re.fullmatch(r"[A-Z]{4}\d{5}", compact):
        return None
    return f"{compact[:4]}-{compact[4:]}"


def normalize_title(value: str) -> str:
    lowered = value.casefold().replace("&", " ").replace("_", " ")
    lowered = re.sub(r"\([^)]*\)", " ", lowered)
    lowered = re.sub(r"\{[^}]*\}", " ", lowered)
    lowered = re.sub(r"[^a-z0-9]+", " ", lowered)
    return " ".join(lowered.split())


def game_title_from_path(path: str) -> str:
    stem = Path(path).stem.replace("_", " ").strip()
    while True:
        stripped = re.sub(r"\s*\([^)]*\)\s*$", "", stem).strip()
        if stripped == stem:
            break
        stem = stripped
    return stem or Path(path).stem


def title_key_from_path(path: str, source_id: str) -> str:
    if source_id == "cookieplmonster-ps1":
        parts = Path(path).parts
        if len(parts) >= 2:
            return normalize_title(parts[1])
    return normalize_title(game_title_from_path(path))


def load_titles_index() -> tuple[dict[str, str], dict[str, list[str]]]:
    data: dict[str, str] = {}
    if TITLES_INDEX_PATH.is_file():
        raw = json.loads(TITLES_INDEX_PATH.read_text(encoding="utf-8"))
        if isinstance(raw, dict):
            for key, value in raw.items():
                if isinstance(value, str):
                    data[str(key)] = value.strip()
    by_title: dict[str, list[str]] = {}
    for serial_key, title in data.items():
        match = SERIAL_NAME_RE.fullmatch(serial_key)
        if match is None:
            continue
        serial = f"{match.group(1).upper()}-{match.group(2)}"
        by_title.setdefault(normalize_title(title), []).append(serial)
    for serials in by_title.values():
        serials.sort(key=serial_rank)
    return data, by_title


def serial_rank(serial: str) -> tuple[int, str]:
    prefix = serial[:4]
    try:
        return (REGION_PRIORITY.index(prefix), serial)
    except ValueError:
        return (len(REGION_PRIORITY), serial)


def resolve_title_serials(
    path: str, text: str, source_id: str, by_title: dict[str, list[str]]
) -> tuple[str, list[str]]:
    key = title_key_from_path(path, source_id)
    override = SERIAL_OVERRIDES.get(key)
    if override:
        return key, sorted(override, key=serial_rank)
    found: set[str] = set()
    for segment in Path(path).stem.split("_"):
        for match in SERIAL_RE.finditer(segment):
            serial = normalize_serial(
                f"{match.group(1)}{match.group(2)}{match.group(3)}"
            )
            if serial:
                found.add(serial)
    if not found:
        for match in SERIAL_NAME_RE.finditer(text):
            serial = normalize_serial(f"{match.group(1)}{match.group(2)}")
            if serial:
                found.add(serial)
    if not found:
        indexed = by_title.get(key)
        if indexed:
            found.update(indexed)
    return key, sorted(found, key=serial_rank)


def parse_libretro_text(text: str) -> dict[str, object] | None:
    descs: dict[int, str] = {}
    codes: dict[int, list[str]] = {}
    for raw_line in text.splitlines():
        stripped = raw_line.strip()
        if not stripped:
            continue
        desc_match = LIBRETRO_DESC_RE.fullmatch(stripped)
        if desc_match is not None:
            descs[int(desc_match.group(1))] = desc_match.group(2).strip()
            continue
        code_match = LIBRETRO_CODE_RE.fullmatch(stripped)
        if code_match is not None:
            index = int(code_match.group(1))
            tokens = [part.strip() for part in code_match.group(2).split("+")]
            valid = []
            for position in range(0, len(tokens) - 1, 2):
                candidate = f"{tokens[position]} {tokens[position + 1]}"
                if RAW_CODE_RE.fullmatch(candidate):
                    valid.append(candidate)
            codes.setdefault(index, []).extend(valid)
    blocks: list[tuple[str, list[str]]] = []
    for index in sorted(set(descs) | set(codes)):
        block_codes = codes.get(index, [])
        if not block_codes:
            continue
        blocks.append((descs.get(index) or f"Cheat {index + 1}", block_codes))
    if not blocks:
        return None
    return {"blocks": blocks}


def parse_block_text(text: str) -> dict[str, object] | None:
    blocks: list[tuple[str, list[str]]] = []
    current_title: str | None = None
    current_codes: list[str] = []
    code_index = 1

    def flush() -> None:
        nonlocal current_title, current_codes, code_index
        if current_codes:
            blocks.append((current_title or f"Cheat {code_index}", current_codes))
            code_index += 1
        current_title = None
        current_codes = []

    for raw_line in text.splitlines():
        stripped = raw_line.strip()
        if not stripped:
            continue
        if stripped.startswith("#"):
            continue
        if stripped.startswith(";"):
            semicolon = stripped[1:].strip()
            if semicolon.startswith("[") and semicolon.endswith("]"):
                flush()
                current_title = semicolon[1:-1].strip()
            continue
        if stripped.startswith("//"):
            label = stripped[2:].strip()
        elif (label_match := LABEL_RE.fullmatch(raw_line)) is not None:
            label = label_match.group(1).strip()
        elif (comment_match := COMMENT_LABEL_RE.fullmatch(raw_line)) is not None:
            label = comment_match.group(1).strip()
        else:
            label = None
        if label:
            flush()
            current_title = label
            continue
        candidate = stripped.split("//", 1)[0].split("#", 1)[0].strip()
        if PLACEHOLDER_RE.fullmatch(candidate):
            continue
        if AUTHOR_RE.fullmatch(candidate) or GAMETITLE_RE.fullmatch(candidate):
            continue
        if METADATA_RE.fullmatch(candidate):
            continue
        if not RAW_CODE_RE.fullmatch(candidate):
            return None
        current_codes.append(candidate)
    flush()
    if not blocks:
        return None
    return {"blocks": blocks}


def parse_cheat_text(text: str) -> dict[str, object] | None:
    if re.search(r"^cheat\d+_code\s*=", text, re.MULTILINE | re.IGNORECASE):
        return parse_libretro_text(text)
    return parse_block_text(text)


def debug_unparsed_reason(text: str) -> str:
    if re.search(r"^cheat\d+_code\s*=", text, re.MULTILINE | re.IGNORECASE):
        return "libretro format without valid code lines"
    for raw_line in text.splitlines():
        stripped = raw_line.strip()
        if not stripped or stripped.startswith("#") or stripped.startswith(";"):
            continue
        if stripped.startswith("//") or LABEL_RE.fullmatch(raw_line):
            continue
        if COMMENT_LABEL_RE.fullmatch(raw_line):
            continue
        candidate = stripped.split("//", 1)[0].strip()
        if AUTHOR_RE.fullmatch(candidate) or GAMETITLE_RE.fullmatch(candidate):
            continue
        if METADATA_RE.fullmatch(candidate):
            continue
        if not RAW_CODE_RE.fullmatch(candidate):
            return f"unexpected line: {candidate!r}"
    return "no code lines"


def code_signature(blocks: list[tuple[str, list[str]]]) -> frozenset[str]:
    return frozenset(
        re.sub(r"\s+", " ", code.strip()).upper()
        for _, codes in blocks
        for code in codes
    )


def archive_files(
    repository: str, revision: str, prefixes: list[str], include: set[str]
) -> list[tuple[str, bytes]]:
    if include:
        files: list[tuple[str, bytes]] = []
        for relative in sorted(include):
            if Path(relative).suffix.lower() not in CHEAT_SUFFIXES:
                continue
            encoded = urllib.parse.quote(relative, safe="/")
            body = fetch(
                f"https://raw.githubusercontent.com/{repository}/{revision}/{encoded}"
            )
            if not 0 < len(body) <= MAX_FILE_BYTES:
                continue
            files.append((relative, body))
        return files
    archive = zipfile.ZipFile(
        io.BytesIO(fetch(f"https://codeload.github.com/{repository}/zip/{revision}"))
    )
    root = archive.namelist()[0].split("/", 1)[0] + "/"
    files = []
    for member in archive.infolist():
        if member.is_dir():
            continue
        relative = member.filename.removeprefix(root)
        if prefixes and not any(
            relative.startswith(prefix) for prefix in prefixes
        ):
            continue
        if Path(relative).suffix.lower() not in CHEAT_SUFFIXES:
            continue
        body = archive.read(member)
        if not 0 < len(body) <= MAX_FILE_BYTES:
            continue
        files.append((relative, body))
    return sorted(files)


def main() -> None:
    if not SOURCES:
        print("No sources configured")
        return
    titles_index, by_title = load_titles_index()
    entries: list[dict[str, object]] = []
    audit_records: list[dict[str, object]] = []
    used_ids: set[str] = set()
    seen_signatures: set[frozenset[str]] = set()
    total_files = 0
    for source in SOURCES:
        source_id = str(source.get("id", ""))
        repository = str(source.get("repository", ""))
        revision = str(source.get("revision", ""))
        if not source_id or not re.fullmatch(r"[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+", repository):
            raise SystemExit(f"Source {source_id!r}: repository must use owner/repo")
        if not REVISION_RE.fullmatch(revision):
            raise SystemExit(
                f"Source {source_id!r}: revision must be a pinned 40-character lowercase Git SHA"
            )
        prefixes = [str(prefix) for prefix in source.get("paths", [])]
        include = {str(path) for path in source.get("include", [])}
        files = archive_files(repository, revision, prefixes, include)
        imported = 0
        skipped_duplicate = 0
        skipped_parse = 0
        for relative_path, body in files:
            total_files += 1
            try:
                text = body.decode("utf-8-sig", errors="strict")
            except UnicodeDecodeError:
                skipped_parse += 1
                continue
            if "\0" in text:
                skipped_parse += 1
                continue
            parsed = parse_cheat_text(text)
            if parsed is None:
                if os.environ.get("EMUCORER_DEBUG"):
                    print(f"  UNPARSED {relative_path}: {debug_unparsed_reason(text)}")
                skipped_parse += 1
                continue
            blocks = list(parsed["blocks"])
            signature = code_signature(blocks)
            if not signature or signature in seen_signatures:
                skipped_duplicate += 1
                continue
            seen_signatures.add(signature)

            title_key, serials = resolve_title_serials(
                relative_path, text, source_id, by_title
            )
            game_title = game_title_from_path(relative_path)
            indexed_title = titles_index.get(serials[0].replace("-", "")) if serials else None
            if indexed_title:
                game_title = indexed_title
            block_titles = unique_titles([name for name, _ in blocks])
            author_values: list[str] = []
            for raw_line in text.splitlines():
                author_match = AUTHOR_RE.fullmatch(raw_line.strip())
                if author_match is not None:
                    author_values.append(author_match.group(1).strip())
            authors = unique_titles(author_values) or [str(source["fallbackAuthor"])]
            description = (
                ", ".join(block_titles[:3])
                if block_titles
                else f"{len(signature)} GameShark/CodeBreaker code lines"
            )
            encoded_path = urllib.parse.quote(relative_path, safe="/")
            if bool(source.get("mirrorFiles")):
                mirror_relative = f"files/{source_id}/{relative_path}"
                download_url = f"{MIRROR_RAW_PREFIX}{source_id}/{encoded_path}"
                mirror_path = (ROOT / "files" / source_id / relative_path).resolve()
                try:
                    mirror_path.relative_to(ROOT.resolve())
                except ValueError as error:
                    raise ValueError(f"Mirror path escapes the repository: {relative_path}") from error
                mirror_path.parent.mkdir(parents=True, exist_ok=True)
                mirror_path.write_bytes(body)
                record_path = mirror_relative
                record_kind = "generated"
            else:
                download_url = (
                    f"https://raw.githubusercontent.com/{repository}/{revision}/{encoded_path}"
                )
                record_path = relative_path
                record_kind = "external"
            source_url = f"https://github.com/{repository}/blob/{revision}/{encoded_path}"
            slug = re.sub(r"[^a-z0-9]+", "-", relative_path.lower()).strip("-")
            entry_id = f"{source_id}-{slug}"
            candidate_id = entry_id
            suffix = 2
            while candidate_id in used_ids:
                candidate_id = f"{entry_id}-{suffix}"
                suffix += 1
            entry_id = candidate_id
            used_ids.add(entry_id)
            entries.append(
                {
                    "id": entry_id,
                    "title": game_title or (block_titles[0] if block_titles else "Cheats"),
                    "serials": serials,
                    "authors": authors,
                    "description": description,
                    "downloadUrl": download_url,
                    "sourceUrl": source_url,
                    "sourceName": str(source["sourceName"]),
                    "license": str(source["license"]),
                    "blockCount": len(block_titles) if block_titles else len(blocks),
                }
            )
            audit_records.append(
                {
                    "kind": record_kind,
                    "path": record_path,
                    "source": repository,
                    "revision": revision,
                    "sizeBytes": len(body),
                    "sha256": hashlib.sha256(body).hexdigest().upper(),
                    "serials": serials,
                    "blockCount": len(block_titles) if block_titles else len(blocks),
                }
            )
            imported += 1
        print(
            f"{source['sourceName']}: {imported}/{len(files)} files imported "
            f"(duplicates={skipped_duplicate}, unparsed={skipped_parse})"
        )
    entries.sort(key=lambda entry: (str(entry["title"]).casefold(), str(entry["id"])))
    generated_at = (
        datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")
    )
    payload = {"schemaVersion": 1, "generatedAt": generated_at, "entries": entries}
    (ROOT / "cheats.json").write_text(
        json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    audit = {
        "batchId": AUDIT_BATCH_ID,
        "verifiedAt": generated_at,
        "entries": audit_records,
    }
    (ROOT / "audits" / f"{AUDIT_BATCH_ID}.json").write_text(
        json.dumps(audit, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    print(f"Total: {len(entries)} entries from {total_files} candidate files")


if __name__ == "__main__":
    main()
