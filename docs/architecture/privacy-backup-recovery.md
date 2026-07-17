# Privacy, backup and recovery

ISSUE-0146 keeps the application local-first while making sensitive local state
portable and recoverable.

## Privacy defaults

Standard exports recursively omit private fields such as private notes,
credentials, tokens and recovery keys. Including those fields requires an
explicit application-level confirmation and remains a local operation. Private
data deletion is scoped to `data/private/` and requires the exact confirmation
phrase `DELETE PRIVATE DATA`.

## Encrypted backups

Encrypted backups use the `cryptography` package's Fernet implementation with
PBKDF2-HMAC-SHA256 and a random per-archive salt. The recovery key is supplied
by the user and is never persisted, logged or included in an archive. Keys
shorter than 16 bytes, wrong keys, malformed headers and corrupted ciphertext
fail closed without writing restored data.

The backup manifest contains SHA-256 checksums, excluded paths and schema
metadata. Incremental archives contain only changed payloads and record the
base manifest checksum. Restore is always previewed and then committed through
the existing atomic write group.

## Recovery evidence

The Settings page exposes encrypted backup creation, validation and a local
disaster-recovery drill. The drill creates an archive, validates it and restores
it into a separate local directory. No network service, broker or external
upload is involved.
