# Local security policy

The application is local-first and fail-closed. `configs/security_policy.yaml`
is the versioned source of truth for network, parser, credential and release
finding controls.

- The Flet UI binds to `127.0.0.1`; the typed application API remains an
  in-process boundary and `http_api_exposed` is `false`.
- Remote access requires HTTPS and an exact host allow-list. Loopback HTTP is
  accepted only when explicitly requested for local readiness checks.
- Local API integrations must use constant-time bearer-token comparison and
  CSRF validation when an HTTP API is introduced.
- Files are regular, non-symlink inputs inside an optional permitted root and
  are read only below the configured byte limit. Existing bulk-cache and ESEF
  parsers retain archive, XML and decompression safeguards.
- Secret-shaped values are redacted recursively before logs, exports or
  diagnostics are persisted. Persistent credentials require an OS keychain or
  encrypted vault; the optional keychain adapter fails closed when unavailable.
- `scripts/check_security_policy.py` writes JSON and Markdown evidence and
  returns a non-zero exit code for unresolved high or critical findings.

Run the check locally with:

```text
python scripts/check_security_policy.py --root .
```
