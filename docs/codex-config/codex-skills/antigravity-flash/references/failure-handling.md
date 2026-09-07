# Failure handling

Begin with 180 seconds for trivial scout, 300 for larger preflight and 480–600
for a bounded editor. The adapter bounds CLI and outer process timeouts.
Reject malformed/missing streams, identity mismatch, unknown or forbidden
tools, denied actions, permission errors, cancellation, waiting/nonterminal
status, quota exhaustion or low-value output. Exit zero is insufficient.

Never blindly retry. Inspect real status/diff even after a rejected editor;
rejection is not rollback. Preserve unexpected changes for root review.
Fallback to the normal V2 role. At most one root-directed correction pass is
allowed for useful, safely bounded output; do not carry sessions across issues.

Unavailable official CLI or signed-in route blocks live evidence only. Do not
install, authenticate, inspect credential stores or switch to API-key/Vertex
billing. Root reports any required manual login. Unsupported tool/init/schema
behavior requires a reviewed official/live fixture before adapter changes;
never generically allow unknown tools. No speculative hooks or MCP bridges.
