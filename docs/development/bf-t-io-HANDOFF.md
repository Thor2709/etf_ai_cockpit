# bf/t-io handoff (T-IO bug-hunt batch)

All 20 listed IDs fixed; none escalated. NEEDS_OPUS_DECISION: none.

## Per ID
- CHAT-P08-N003 fixed: `_strict_bool` (non-bool -> `SecurityPolicyError`); report fails on `default_deny` off or exposed API without auth/CSRF.
- CHAT-P08-N004 fixed: one `SECRET_KEY_RE` (adds private/signing key, credential); used by `redact_secrets` (`.search`) and `session_log._redact`. It is defined in `core/session_log.py` and re-exported by `security/policy.py` (policy already imports session_log, so the plan's direction would be circular).
- CHAT-P08-N006 fixed: files over `MAX_TEXT_FILE_BYTES` yield `UNSCANNED_TOO_LARGE` (check moved from `_iter_scannable_files` into the scan loop).
- CHAT-P08-N007 fixed: extraction reads one open handle, re-hashes it against the manifest and hashes every member while copying; staging is removed on any failure.
- CHAT-P08-N008 fixed: `_safe_member` rejects empty `parts` (`"."`).
- P01-N006 fixed: H:noredirect = `core/http_fetch.get_checked` (+ `NoRedirect`), moved from `etf_e1_fetch._get`; OAM (incl. Companies House) and ESEF `_get` use it with their host allowlist.
- P02-N003 fixed: `_safe_name` appends `-<sha256(raw)[:12]>` only when cleaning changed the name.
- P02-N004 fixed: an existing object is trusted only when its hash equals the digest; otherwise the verified part replaces it.
- P02-N009 fixed: incremental manifest has `deleted`; incremental restore removes those names (paths validated inside the approved roots).
- P02-N012 fixed: `validate_restore` runs the `bulk_cache._validate_archive_members` limits on `infolist()` before any read (`archive_limits_exceeded:...`).
- P02-N013 fixed: `BackupError("archive_name_collision:<name>")`.
- P02-N014 fixed: response `total_size` must equal bytes written in this call.
- P02-N015 fixed: `_iter_files` returns (files, skipped); symlinks/junctions/reparse points and items resolving outside the root are skipped and listed in `excluded`.
- P07-N015 fixed: `export_review_pack` stages into `<name>.staging-<uuid8>` (`_stage_review_pack`), zips from staging, then swaps the directory with `os.replace`.
- P07-N020 fixed: the zip is built in `BytesIO` and published with `atomic_write_bytes`.
- P08-N001 fixed: all `data\*` copy lines removed from `build_windows.bat` (empty `data` dir only).
- P08-N002 fixed: `sha256_file` (streamed), `MAX_ARCHIVE_BYTES` stat check, member count/expanded/ratio limits in `_file_infos` before any member is read. Limits are local constants in `core/secure_update.py` (same values as `bulk_cache`) because `core` importing `data.bulk_cache` is a new layering violation (`tests/test_import_layering.py`).
- P08-N003 fixed: certification returns `blocked` unless `ETF_COCKPIT_RELEASE_SIGNING_KEY` is set (>=16 bytes) and the detached HMAC over the manifest bytes verifies (`secure_update.detached_signature_errors`, now shared by `verify_update_bundle`).
- P08-N005 fixed: `:copy_required` subroutine (`|| exit /b 1` semantics via errorlevel) for src, configs, scripts, README/requirements files and the native dist copy.
- P08-N006 fixed: with `ETF_COCKPIT_RELEASE_BUILD=1` the launcher installs `requirements-release.txt` / `requirements-release-parsers.txt` and those files are copied.

## Existing test changed
- `tests/ui/test_oam_discovery_ui.py`: the no-network guard now patches `urllib.request.build_opener` instead of the removed `oam_adapters.urlopen` (same assertion).

## Tests
`python -m pytest -q --tb=line -p no:cacheprovider tests/test_bugfix_t-io.py` -> 26 passed (P02-N015 falls back to a directory junction when symlinks are not permitted on Windows).
Existing suites of the changed modules (plus bughunt, e2e_advanced, release_hardening, governance_review_regressions, trust_critical, launcher, credentials, workflow_runtime, canary, ui page tests; secure_update, security_policy, backup_restore, bulk_cache, esef, etf_live_fetch, oam, release_certification, build_windows, scope_boundary, redaction, sec_bulk_*, complete_audit_packet, release_gate, architecture_boundaries, ui oam): green except base failures listed in `gate-fails-1b733dc4.txt` (3 in `test_backup_restore.py`, `test_import_layering.py::test_no_new_layering_violations` for 4 pre-existing pairs; the `core.secure_update -> data.bulk_cache` pair introduced and then removed).

## Files changed
scripts/build_windows.bat; chatgpt_bridge/export_pack.py; core/secure_update.py, core/session_log.py, core/http_fetch.py (new); data/backup_restore.py, bulk_cache.py, esef_provider.py, etf_e1_fetch.py, oam_adapters.py; governance/release_certification.py, static_checks.py; security/policy.py; tests/test_bugfix_t-io.py (new); tests/ui/test_oam_discovery_ui.py.
