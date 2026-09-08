# Historical control-plane records

These files preserve the exact accepted-main bytes at
`51bec2b8937f725e9e1c74136249a1d9c7d4851a` before the control-plane remediation.
They are evidence, not current instructions, active ownership or live machine
state. Relative links inside them retain their original historical context;
resolve against the source commit where needed. `manifest.json` records original
paths, Git blobs and byte hashes. Nothing here confers execution or merge authority.

The existing reconciliation directories, validation artifacts and PR branches
remain preserved. Do not load this archive at ordinary session startup. Search
only when an issue card, historical work locator or an actual failure requires it.

The root instruction snapshot uses `AGENTS.snapshot.md`, not an auto-discovered `AGENTS.md` filename. Its bytes remain identical.
