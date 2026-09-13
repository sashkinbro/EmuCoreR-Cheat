# Contributing cheats

Each entry must identify the game, its PlayStation 1 serial(s) when known, the
original author or collection, and a stable HTTPS download URL. Prefer raw
files from the author's GitHub repository, pinned to an immutable 40-character
commit.

Do not mirror third-party files without the author's permission or an explicit
license allowing redistribution. Attribution does not replace permission.

Requirements:

1. Cheat files are UTF-8 text. Supported layouts are plain text with optional
   `gametitle=`/`author=` lines and titled blocks written as `// Title`,
   `[Title]` or `comment=Title`; libretro `cht` files with `cheatN_desc` and
   `cheatN_code` entries; and DuckStation `cht` files with `[Block Name]`
   sections.
2. Every code line is a raw GameShark/CodeBreaker code: 8 hex address, 1-8 hex
   value, separated by whitespace, `:`, `+` or `-`. PNACH `patch=` lines are
   not part of this catalog.
3. At least one active raw code line is present and every active line is
   parseable by the app.
4. `authors` must not be empty. `serials` are PS1 `XXXX-#####` values and may
   be empty; `crc` is optional and must be eight uppercase hex characters when
   present.
5. Every entry includes `sourceUrl` and `downloadUrl`, both HTTPS.
6. Non-mirrored curated files use a 40-character pinned Git commit and add a
   batch record under `audits` with source path, byte size and SHA-256.
7. Mirrored files live under `files/<source-id>/` only when redistribution is
   explicitly allowed, and the `downloadUrl` points at the repository mirror.
8. Generated files must be reproducible from a pinned, redistribution-
   compatible source; the audit records the generated hash, license, serials
   and optional CRC evidence.
9. Duplicate detection is based on the CRC (or serial list when no CRC is
   known) plus the normalized set of active code lines: named, line-ending-only
   and near-identical copies of an existing pack are rejected.
10. The app merges catalog packs instead of replacing installed cheats, so
    prefer distinct content over renamed duplicates.

Run the validators before opening a pull request:

```bash
python scripts/import_ps1_collection.py
python scripts/validate_catalog.py
python scripts/validate_audits.py
python scripts/verify_audit_live.py --batch-id batch-NNN
```

The live verifier requires network access. The other commands are offline and
dependency-free.
