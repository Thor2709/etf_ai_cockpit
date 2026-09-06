# ISSUE-0043 Documentation Strategy

The user-facing documentation has two synchronized surfaces:

1. `docs/user/manual.md` is the versioned, reviewable manual for onboarding,
   methodology, score interpretation, authority vocabulary, limitations, and
   the glossary.
2. `/help` is the in-app searchable surface. Its page guidance is maintained as
   typed content in `app/content/user_guidance.py`, and its financial/governance
   terms remain loaded from the canonical `configs/glossary.yaml` policy.

The route contract is intentionally explicit: every registered page route must
have at least one guidance topic, and unknown routes must return no guidance so
the UI can show an unavailable state instead of inventing instructions.

When a route, score, authority state, or safety invariant changes, update the
content contract, manual, and focused smoke tests together. The tests must
cover the required glossary vocabulary, score bands, authority states,
`N/A` semantics, route coverage, help rendering, and
`execution_allowed=false`. Documentation changes never modify financial
calculations, persistence, provider behavior, broker behavior, or execution
authority.
