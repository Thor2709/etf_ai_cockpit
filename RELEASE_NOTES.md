# ETF AI Cockpit 0.1.0rc1

This describes a release candidate, not completion or certification of the
final multi-asset programme. See the [current SDD](docs/architecture/SDD.md).

## Install and first run

1. Download and extract the complete `ETF_AI_Cockpit_Portable_v0.1.0rc1.zip`
   to a writable directory.
2. Double-click `Run_ETF_AI_Cockpit_EXE.bat`.
3. The launcher starts the bundled `native\\ETF_AI_Cockpit\\ETF_AI_Cockpit.exe`,
   selects or reuses a local port, and opens the local browser page.
4. User data is written below the extracted release directory. Do not run the
   executable from inside the ZIP archive.

The release does not require Python for the native launcher. The source
launcher and dependency manifests are included for development and recovery,
but are not required for the packaged path.

## Availability and safety

Core local workflows are packaged with deterministic sample/fallback data and
the configured schemas. Internet-backed provider refreshes require network
access and any provider-specific API key; missing credentials are shown as
unavailable rather than treated as evidence. TimesFM and Toto are optional and
require their external model locations. No broker connection or automatic
trading execution is included; `execution_allowed` remains `false`.

This is a release candidate. The full programme still contains open issue
dossiers whose strict closure evidence is being completed after the release.
