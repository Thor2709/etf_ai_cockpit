# Training Centre

ISSUE-0117 adds a local experiment and model-governance adapter over the
existing transactional SQLite store. The adapter records experiments, runs,
parameters, metrics, datasets, artefacts, models, approval state and aliases.
It also records dataset, feature, code and environment hashes so a run can be
checked for offline replay after an application restart.

Training work is submitted through the existing durable job scheduler. A job
mirrors queued, running, completed, failed and cancelled state into its run
record. Cancellation and failure therefore cannot publish a completion report
or model alias.

Model files are never deserialised by this slice. Artefacts must be inside the
user-owned `models/` or `data/` directories, are checksum-verified, and known
unsafe Python serialisation formats are rejected. Parameters, model cards,
evaluation details and job output are bounded and secret-redacted before
persistence.

Only a completed run with verified artefacts and explicit human approval can
become a challenger or champion. `execution_allowed=false` remains a hard
boundary: promotion is research evidence only and cannot submit orders.

The `/training-centre` page exposes durable run status, metrics, model
comparison, aliases and completion reports. Full training algorithms,
leakage-safe evaluation, champion selection and optional MLflow integration
remain later issue work; the local adapter is intentionally compatible with a
future backend without adding a production dependency now.
