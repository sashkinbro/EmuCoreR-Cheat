# EmuCoreR Cheat Catalog

Community-maintained PlayStation 1 cheat catalog consumed by the EmuCoreR
cheat manager. EmuCoreR runs a DuckStation-compatible PS1 core on Android.

The repository stores catalog metadata and validation tools. Raw
GameShark/CodeBreaker text files are mirrored when redistribution permits it;
otherwise the catalog uses immutable upstream commit URLs. Every entry
preserves authorship and its original source URL while branch changes cannot
alter the reviewed file. The app merges catalog packs into the cheats already
installed for a game instead of overwriting them.

## Files

- `cheats.json` - production catalog used by EmuCoreR.
- `sources.json` - approved upstream collections and their attribution.
- `schemas/cheat-catalog.schema.json` - public format contract.
- `files` - mirrored GameShark/CodeBreaker text grouped by credited source.
- `scripts/import_ps1_collection.py` - reproducible multi-source catalog importer.
- `scripts/ps1_titles.json` - PlayStation serial to title index used to map
  imported files to the exact regional serials.
- `scripts/validate_catalog.py` - dependency-free catalog validator.
- `scripts/validate_audits.py` - verifies pinned batches and content-hash deduplication.
- `scripts/verify_audit_live.py` - downloads and strictly checks every external file in an audit.
- `audits` - immutable source, size and SHA-256 records for curated batches.
- `LICENSES` - license texts for redistributed or generated source-derived packs.

## Sources and attribution

Every entry keeps its original author credit, source name, source URL, license
and the exact upstream revision so mirrored bytes can always be traced back.

| Source | License | Mode |
|---|---|---|
| [libretro-database](https://github.com/libretro/libretro-database) PlayStation cheats | CC-BY-SA-4.0 | mirrored under `files/libretro-ps1/` with attribution; adaptations keep the same license |
| [CookiePLMonster/Console-Cheat-Codes](https://github.com/CookiePLMonster/Console-Cheat-Codes) | MIT | mirrored under `files/cookieplmonster-ps1/` with attribution |
| [duckstation/chtdb](https://github.com/duckstation/chtdb) | Cheat data copyright the original authors; scripts MIT | linked only through immutable pinned upstream URLs |

Cheat data that is not explicitly redistributable is never mirrored; the
catalog stores only a pinned raw URL for it. See
[CONTRIBUTING.md](CONTRIBUTING.md) before mirroring new content.

## Cheat format

Catalog downloads are UTF-8 text. Three layouts are supported and parsed by
the app:

- Plain text with optional `gametitle=`/`author=` lines and titled blocks
  written as `// Title`, `[Title]` or `comment=Title`.
- libretro `cht` files with `cheats = N`, `cheatN_desc = "..."` and
  `cheatN_code = "ADDR+VALUE+ADDR+VALUE"` entries.
- DuckStation `cht` files with `[Block Name]` sections and raw code lines
  (metadata keys such as `Type` and `Activation` are ignored).

Each block contains raw GameShark/CodeBreaker code lines with an 8 hex address
and a 1-8 hex value separated by whitespace, `:`, `+` or `-`:

```text
gametitle=Crash Bandicoot (SCUS-94900)
author=Example Author

// Infinite Lives
80012345 0009
```

The app parses these blocks and converts the raw codes into the core's `.cht`
format. The catalog itself never ships PNACH files.

## Updating the upstream catalog

```bash
python scripts/import_ps1_collection.py
python scripts/validate_catalog.py
python scripts/validate_audits.py
python scripts/verify_audit_live.py --batch-id batch-NNN
```

Add sources to the `SOURCES` table in `scripts/import_ps1_collection.py`, each
pinned to a 40-character commit. The importer downloads the pinned archive,
keeps only raw-code `.txt`/`.cht` files, parses titles, authors and PS1
serials, applies optional audit overrides, mirrors bytes only for sources
whose license permits redistribution, and writes a sorted `cheats.json`.

Non-mirrored entries point at immutable upstream raw URLs and are recorded in
`audits/batch-NNN.json` with the source path, byte size and SHA-256 hash.
`scripts/validate_audits.py` cross-checks each record against the catalog, and
`scripts/verify_audit_live.py` re-downloads the pinned files to confirm size,
hash, code syntax, block counts and duplicate-free rotation.

See [CONTRIBUTING.md](CONTRIBUTING.md) before adding or mirroring content.
