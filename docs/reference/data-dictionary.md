# Data dictionary

Release version: `0.1.0rc1`.

Generated with `python scripts/generate_data_dictionary.py`. Regenerate after a contract change; use `python scripts/generate_data_dictionary.py --check` to detect drift.

## SQLite tables

| Table | Column | Type | Constraints | Defining module |
| --- | --- | --- | --- | --- |
| analytical_generation_keys | <table constraint> | — | FOREIGN KEY(dataset_id, generation_id) REFERENCES analytical_generations(dataset_id, generation_id) ON DELETE CASCADE | etf_cockpit/data/local_storage.py |
| analytical_generation_keys | <table constraint> | — | PRIMARY KEY(dataset_id, generation_id, stable_id, run_id) | etf_cockpit/data/local_storage.py |
| analytical_generation_keys | dataset_id | TEXT | NOT NULL | etf_cockpit/data/local_storage.py |
| analytical_generation_keys | generation_id | TEXT | NOT NULL | etf_cockpit/data/local_storage.py |
| analytical_generation_keys | run_id | TEXT | NOT NULL | etf_cockpit/data/local_storage.py |
| analytical_generation_keys | stable_id | TEXT | NOT NULL | etf_cockpit/data/local_storage.py |
| analytical_generations | <table constraint> | — | PRIMARY KEY(dataset_id, generation_id) | etf_cockpit/data/local_storage.py |
| analytical_generations | columns_json | TEXT | NOT NULL | etf_cockpit/data/local_storage.py |
| analytical_generations | committed_at | TEXT | NOT NULL | etf_cockpit/data/local_storage.py |
| analytical_generations | dataset_id | TEXT | NOT NULL | etf_cockpit/data/local_storage.py |
| analytical_generations | generation_id | TEXT | NOT NULL | etf_cockpit/data/local_storage.py |
| analytical_generations | relative_path | TEXT | NOT NULL UNIQUE | etf_cockpit/data/local_storage.py |
| analytical_generations | row_count | INTEGER | NOT NULL CHECK (row_count >= 0) | etf_cockpit/data/local_storage.py |
| analytical_generations | run_id_count | INTEGER | NOT NULL CHECK (run_id_count >= 0) | etf_cockpit/data/local_storage.py |
| analytical_generations | sha256 | TEXT | NOT NULL | etf_cockpit/data/local_storage.py |
| analytical_generations | stable_id_count | INTEGER | NOT NULL CHECK (stable_id_count >= 0) | etf_cockpit/data/local_storage.py |
| analytical_generations | status | TEXT | NOT NULL CHECK (status IN ('publishing', 'published')) | etf_cockpit/data/local_storage.py |
| bitemporal_observations | <table constraint> | — | UNIQUE(dataset_id, stable_id, source_id, revision) | etf_cockpit/data/local_storage.py |
| bitemporal_observations | availability_confidence | TEXT | NOT NULL CHECK (availability_confidence IN ('exact', 'inferred')) | etf_cockpit/data/local_storage.py |
| bitemporal_observations | available_at | TEXT | NOT NULL | etf_cockpit/data/local_storage.py |
| bitemporal_observations | dataset_id | TEXT | NOT NULL | etf_cockpit/data/local_storage.py |
| bitemporal_observations | entity_id | TEXT | NOT NULL | etf_cockpit/data/local_storage.py |
| bitemporal_observations | ingested_at | TEXT | NOT NULL | etf_cockpit/data/local_storage.py |
| bitemporal_observations | observation_id | TEXT | PRIMARY KEY | etf_cockpit/data/local_storage.py |
| bitemporal_observations | observed_at | TEXT | NOT NULL | etf_cockpit/data/local_storage.py |
| bitemporal_observations | published_at | TEXT | NOT NULL | etf_cockpit/data/local_storage.py |
| bitemporal_observations | revised_at | TEXT | — | etf_cockpit/data/local_storage.py |
| bitemporal_observations | revision | INTEGER | NOT NULL CHECK (revision > 0) | etf_cockpit/data/local_storage.py |
| bitemporal_observations | run_id | TEXT | NOT NULL | etf_cockpit/data/local_storage.py |
| bitemporal_observations | source_checksum | TEXT | NOT NULL | etf_cockpit/data/local_storage.py |
| bitemporal_observations | source_id | TEXT | NOT NULL | etf_cockpit/data/local_storage.py |
| bitemporal_observations | stable_id | TEXT | NOT NULL | etf_cockpit/data/local_storage.py |
| bitemporal_observations | status | TEXT | NOT NULL CHECK (status IN ('active', 'retracted', 'superseded')) | etf_cockpit/data/local_storage.py |
| bitemporal_observations | timezone_confidence | TEXT | NOT NULL CHECK (timezone_confidence IN ('exact', 'normalised', 'unknown')) | etf_cockpit/data/local_storage.py |
| bitemporal_observations | valid_from | TEXT | NOT NULL | etf_cockpit/data/local_storage.py |
| bitemporal_observations | valid_to | TEXT | — | etf_cockpit/data/local_storage.py |
| bitemporal_observations | value_json | TEXT | NOT NULL | etf_cockpit/data/local_storage.py |
| capture_log | capture_id | INTEGER | PRIMARY KEY AUTOINCREMENT | etf_cockpit/data/universe_membership.py |
| capture_log | checksum | TEXT | NOT NULL | etf_cockpit/data/universe_membership.py |
| capture_log | complete | INTEGER | NOT NULL | etf_cockpit/data/universe_membership.py |
| capture_log | known_at | TEXT | NOT NULL | etf_cockpit/data/universe_membership.py |
| capture_log | licence_ref | TEXT | — | etf_cockpit/data/universe_membership.py |
| capture_log | raw_path | TEXT | NOT NULL | etf_cockpit/data/universe_membership.py |
| capture_log | row_count | INTEGER | NOT NULL | etf_cockpit/data/universe_membership.py |
| capture_log | scope | TEXT | NOT NULL | etf_cockpit/data/universe_membership.py |
| capture_log | snapshot_date | TEXT | NOT NULL | etf_cockpit/data/universe_membership.py |
| capture_log | source | TEXT | NOT NULL | etf_cockpit/data/universe_membership.py |
| capture_log | source_id | TEXT | NOT NULL | etf_cockpit/data/universe_membership.py |
| capture_log | source_kind | TEXT | NOT NULL | etf_cockpit/data/universe_membership.py |
| durable_job_dependencies | <table constraint> | — | CHECK(job_id <> dependency_job_id) | etf_cockpit/data/local_storage.py |
| durable_job_dependencies | <table constraint> | — | FOREIGN KEY(dependency_job_id) REFERENCES durable_jobs(job_id) ON DELETE CASCADE | etf_cockpit/data/local_storage.py |
| durable_job_dependencies | <table constraint> | — | FOREIGN KEY(job_id) REFERENCES durable_jobs(job_id) ON DELETE CASCADE | etf_cockpit/data/local_storage.py |
| durable_job_dependencies | <table constraint> | — | PRIMARY KEY(job_id, dependency_job_id) | etf_cockpit/data/local_storage.py |
| durable_job_dependencies | dependency_job_id | TEXT | NOT NULL | etf_cockpit/data/local_storage.py |
| durable_job_dependencies | job_id | TEXT | NOT NULL | etf_cockpit/data/local_storage.py |
| durable_job_events | <table constraint> | — | FOREIGN KEY(job_id) REFERENCES durable_jobs(job_id) ON DELETE CASCADE | etf_cockpit/data/local_storage.py |
| durable_job_events | <table constraint> | — | FOREIGN KEY(workflow_id) REFERENCES workflow_runs(workflow_id) ON DELETE CASCADE | etf_cockpit/data/local_storage.py |
| durable_job_events | event_hash | TEXT | NOT NULL UNIQUE | etf_cockpit/data/local_storage.py |
| durable_job_events | event_id | INTEGER | PRIMARY KEY AUTOINCREMENT | etf_cockpit/data/local_storage.py |
| durable_job_events | event_type | TEXT | NOT NULL | etf_cockpit/data/local_storage.py |
| durable_job_events | job_id | TEXT | — | etf_cockpit/data/local_storage.py |
| durable_job_events | occurred_at | TEXT | NOT NULL | etf_cockpit/data/local_storage.py |
| durable_job_events | payload_json | TEXT | NOT NULL | etf_cockpit/data/local_storage.py |
| durable_job_events | previous_hash | TEXT | NOT NULL | etf_cockpit/data/local_storage.py |
| durable_job_events | status | TEXT | NOT NULL | etf_cockpit/data/local_storage.py |
| durable_job_events | workflow_id | TEXT | NOT NULL | etf_cockpit/data/local_storage.py |
| durable_jobs | <table constraint> | — | FOREIGN KEY(workflow_id) REFERENCES workflow_runs(workflow_id) ON DELETE CASCADE | etf_cockpit/data/local_storage.py |
| durable_jobs | <table constraint> | — | UNIQUE(workflow_id, job_key) | etf_cockpit/data/local_storage.py |
| durable_jobs | cancel_requested | INTEGER | NOT NULL DEFAULT 0 CHECK (cancel_requested IN (0, 1)) | etf_cockpit/data/local_storage.py |
| durable_jobs | checkpoint_json | TEXT | NOT NULL | etf_cockpit/data/local_storage.py |
| durable_jobs | created_at | TEXT | NOT NULL | etf_cockpit/data/local_storage.py |
| durable_jobs | error_fingerprint | TEXT | — | etf_cockpit/data/local_storage.py |
| durable_jobs | error_message | TEXT | NOT NULL DEFAULT '' | etf_cockpit/data/local_storage.py |
| durable_jobs | finished_at | TEXT | — | etf_cockpit/data/local_storage.py |
| durable_jobs | heartbeat_at | TEXT | — | etf_cockpit/data/local_storage.py |
| durable_jobs | input_hash | TEXT | NOT NULL | etf_cockpit/data/local_storage.py |
| durable_jobs | inputs_json | TEXT | NOT NULL | etf_cockpit/data/local_storage.py |
| durable_jobs | job_id | TEXT | PRIMARY KEY | etf_cockpit/data/local_storage.py |
| durable_jobs | job_key | TEXT | NOT NULL | etf_cockpit/data/local_storage.py |
| durable_jobs | label | TEXT | NOT NULL | etf_cockpit/data/local_storage.py |
| durable_jobs | lease_expires_at | TEXT | — | etf_cockpit/data/local_storage.py |
| durable_jobs | lease_owner | TEXT | NOT NULL DEFAULT '' | etf_cockpit/data/local_storage.py |
| durable_jobs | max_retries | INTEGER | NOT NULL CHECK (max_retries >= 0) | etf_cockpit/data/local_storage.py |
| durable_jobs | outputs_json | TEXT | NOT NULL | etf_cockpit/data/local_storage.py |
| durable_jobs | resource_json | TEXT | NOT NULL | etf_cockpit/data/local_storage.py |
| durable_jobs | retry_count | INTEGER | NOT NULL CHECK (retry_count >= 0) | etf_cockpit/data/local_storage.py |
| durable_jobs | retryable | INTEGER | NOT NULL DEFAULT 0 CHECK (retryable IN (0, 1)) | etf_cockpit/data/local_storage.py |
| durable_jobs | started_at | TEXT | — | etf_cockpit/data/local_storage.py |
| durable_jobs | status | TEXT | NOT NULL CHECK (status IN ('queued', 'running', 'succeeded', 'failed', 'cancelled', 'blocked')) | etf_cockpit/data/local_storage.py |
| durable_jobs | workflow_id | TEXT | NOT NULL | etf_cockpit/data/local_storage.py |
| interval_revisions | capture_id | INTEGER | NOT NULL | etf_cockpit/data/universe_membership.py |
| interval_revisions | instrument_id | TEXT | NOT NULL | etf_cockpit/data/universe_membership.py |
| interval_revisions | interval_id | TEXT | NOT NULL | etf_cockpit/data/universe_membership.py |
| interval_revisions | known_at | TEXT | NOT NULL | etf_cockpit/data/universe_membership.py |
| interval_revisions | revision_id | INTEGER | PRIMARY KEY AUTOINCREMENT | etf_cockpit/data/universe_membership.py |
| interval_revisions | scope | TEXT | NOT NULL | etf_cockpit/data/universe_membership.py |
| interval_revisions | source | TEXT | NOT NULL | etf_cockpit/data/universe_membership.py |
| interval_revisions | source_id | TEXT | NOT NULL | etf_cockpit/data/universe_membership.py |
| interval_revisions | source_kind | TEXT | NOT NULL | etf_cockpit/data/universe_membership.py |
| interval_revisions | valid_from | TEXT | NOT NULL | etf_cockpit/data/universe_membership.py |
| interval_revisions | valid_to | TEXT | — | etf_cockpit/data/universe_membership.py |
| ledger_accounts | <table constraint> | — | CHECK(parent_account_id IS NULL OR parent_account_id <> account_id) | etf_cockpit/data/local_storage.py |
| ledger_accounts | <table constraint> | — | CHECK(parent_account_id IS NULL OR parent_account_id <> account_id) | etf_cockpit/data/local_storage.py |
| ledger_accounts | <table constraint> | — | CHECK(parent_account_id IS NULL OR parent_account_id <> account_id) | etf_cockpit/data/local_storage.py |
| ledger_accounts | <table constraint> | — | FOREIGN KEY(parent_account_id, authority) REFERENCES ledger_accounts(account_id, authority) | etf_cockpit/data/local_storage.py |
| ledger_accounts | <table constraint> | — | FOREIGN KEY(parent_account_id, authority) REFERENCES ledger_accounts(account_id, authority) | etf_cockpit/data/local_storage.py |
| ledger_accounts | <table constraint> | — | FOREIGN KEY(parent_account_id, authority) REFERENCES ledger_accounts(account_id, authority) | etf_cockpit/data/local_storage.py |
| ledger_accounts | <table constraint> | — | PRIMARY KEY(account_id, authority) | etf_cockpit/data/local_storage.py |
| ledger_accounts | <table constraint> | — | PRIMARY KEY(account_id, authority) | etf_cockpit/data/local_storage.py |
| ledger_accounts | <table constraint> | — | UNIQUE(account_id, authority) | etf_cockpit/data/local_storage.py |
| ledger_accounts | account_id | TEXT | NOT NULL | etf_cockpit/data/local_storage.py |
| ledger_accounts | account_id | TEXT | NOT NULL | etf_cockpit/data/local_storage.py |
| ledger_accounts | account_id | TEXT | PRIMARY KEY | etf_cockpit/data/local_storage.py |
| ledger_accounts | account_role | TEXT | NOT NULL DEFAULT 'general' CHECK(account_role IN ('general', 'cash', 'position')) | etf_cockpit/data/local_storage.py |
| ledger_accounts | account_type | TEXT | NOT NULL CHECK(account_type IN ('asset', 'liability', 'equity', 'income', 'expense')) | etf_cockpit/data/local_storage.py |
| ledger_accounts | account_type | TEXT | NOT NULL CHECK(account_type IN ('asset', 'liability', 'equity', 'income', 'expense')) | etf_cockpit/data/local_storage.py |
| ledger_accounts | account_type | TEXT | NOT NULL CHECK(account_type IN ('asset', 'liability', 'equity', 'income', 'expense')) | etf_cockpit/data/local_storage.py |
| ledger_accounts | authority | TEXT | NOT NULL CHECK(authority IN ('paper', 'broker')) | etf_cockpit/data/local_storage.py |
| ledger_accounts | authority | TEXT | NOT NULL CHECK(authority IN ('paper', 'broker')) | etf_cockpit/data/local_storage.py |
| ledger_accounts | authority | TEXT | NOT NULL CHECK(authority IN ('paper', 'broker')) | etf_cockpit/data/local_storage.py |
| ledger_accounts | created_at | TEXT | NOT NULL | etf_cockpit/data/local_storage.py |
| ledger_accounts | created_at | TEXT | NOT NULL | etf_cockpit/data/local_storage.py |
| ledger_accounts | created_at | TEXT | NOT NULL | etf_cockpit/data/local_storage.py |
| ledger_accounts | name | TEXT | NOT NULL CHECK(length(trim(name)) > 0) | etf_cockpit/data/local_storage.py |
| ledger_accounts | name | TEXT | NOT NULL CHECK(length(trim(name)) > 0) | etf_cockpit/data/local_storage.py |
| ledger_accounts | name | TEXT | NOT NULL CHECK(length(trim(name)) > 0) | etf_cockpit/data/local_storage.py |
| ledger_accounts | parent_account_id | TEXT | — | etf_cockpit/data/local_storage.py |
| ledger_accounts | parent_account_id | TEXT | — | etf_cockpit/data/local_storage.py |
| ledger_accounts | parent_account_id | TEXT | — | etf_cockpit/data/local_storage.py |
| ledger_entries | <table constraint> | — | CHECK(reversal_of_entry_id IS NULL OR reversal_of_entry_id <> entry_id) | etf_cockpit/data/local_storage.py |
| ledger_entries | <table constraint> | — | CHECK(reversal_of_entry_id IS NULL OR reversal_of_entry_id <> entry_id) | etf_cockpit/data/local_storage.py |
| ledger_entries | <table constraint> | — | CHECK(reversal_of_entry_id IS NULL OR reversal_of_entry_id <> entry_id) | etf_cockpit/data/local_storage.py |
| ledger_entries | <table constraint> | — | FOREIGN KEY(reversal_of_entry_id, authority) REFERENCES ledger_entries(entry_id, authority) | etf_cockpit/data/local_storage.py |
| ledger_entries | <table constraint> | — | FOREIGN KEY(reversal_of_entry_id, authority) REFERENCES ledger_entries(entry_id, authority) | etf_cockpit/data/local_storage.py |
| ledger_entries | <table constraint> | — | FOREIGN KEY(reversal_of_entry_id, authority) REFERENCES ledger_entries(entry_id, authority) | etf_cockpit/data/local_storage.py |
| ledger_entries | <table constraint> | — | PRIMARY KEY(entry_id, authority) | etf_cockpit/data/local_storage.py |
| ledger_entries | <table constraint> | — | PRIMARY KEY(entry_id, authority) | etf_cockpit/data/local_storage.py |
| ledger_entries | <table constraint> | — | UNIQUE(entry_id, authority) | etf_cockpit/data/local_storage.py |
| ledger_entries | <table constraint> | — | UNIQUE(reversal_of_entry_id, authority) | etf_cockpit/data/local_storage.py |
| ledger_entries | <table constraint> | — | UNIQUE(reversal_of_entry_id, authority) | etf_cockpit/data/local_storage.py |
| ledger_entries | authority | TEXT | NOT NULL CHECK(authority IN ('paper', 'broker')) | etf_cockpit/data/local_storage.py |
| ledger_entries | authority | TEXT | NOT NULL CHECK(authority IN ('paper', 'broker')) | etf_cockpit/data/local_storage.py |
| ledger_entries | authority | TEXT | NOT NULL CHECK(authority IN ('paper', 'broker')) | etf_cockpit/data/local_storage.py |
| ledger_entries | description | TEXT | NOT NULL DEFAULT '' | etf_cockpit/data/local_storage.py |
| ledger_entries | description | TEXT | NOT NULL DEFAULT '' | etf_cockpit/data/local_storage.py |
| ledger_entries | description | TEXT | NOT NULL DEFAULT '' | etf_cockpit/data/local_storage.py |
| ledger_entries | effective_at | TEXT | NOT NULL CHECK(length(trim(effective_at)) > 0) | etf_cockpit/data/local_storage.py |
| ledger_entries | effective_at | TEXT | NOT NULL CHECK(length(trim(effective_at)) > 0) | etf_cockpit/data/local_storage.py |
| ledger_entries | effective_at | TEXT | NOT NULL CHECK(length(trim(effective_at)) > 0) | etf_cockpit/data/local_storage.py |
| ledger_entries | entry_id | TEXT | NOT NULL | etf_cockpit/data/local_storage.py |
| ledger_entries | entry_id | TEXT | NOT NULL | etf_cockpit/data/local_storage.py |
| ledger_entries | entry_id | TEXT | PRIMARY KEY | etf_cockpit/data/local_storage.py |
| ledger_entries | recorded_at | TEXT | NOT NULL | etf_cockpit/data/local_storage.py |
| ledger_entries | recorded_at | TEXT | NOT NULL | etf_cockpit/data/local_storage.py |
| ledger_entries | recorded_at | TEXT | NOT NULL | etf_cockpit/data/local_storage.py |
| ledger_entries | reversal_of_entry_id | TEXT | — | etf_cockpit/data/local_storage.py |
| ledger_entries | reversal_of_entry_id | TEXT | — | etf_cockpit/data/local_storage.py |
| ledger_entries | reversal_of_entry_id | TEXT | UNIQUE | etf_cockpit/data/local_storage.py |
| ledger_entries | settlement_at | TEXT | CHECK(settlement_at IS NULL OR length(trim(settlement_at)) > 0) | etf_cockpit/data/local_storage.py |
| ledger_entries | status | TEXT | NOT NULL CHECK(status IN ('posting', 'posted')) | etf_cockpit/data/local_storage.py |
| ledger_entries | status | TEXT | NOT NULL CHECK(status IN ('posting', 'posted')) | etf_cockpit/data/local_storage.py |
| ledger_entries | status | TEXT | NOT NULL CHECK(status IN ('posting', 'posted')) | etf_cockpit/data/local_storage.py |
| ledger_postings | <table constraint> | — | CHECK( (currency IS NOT NULL AND currency GLOB '[A-Z][A-Z][A-Z]' AND ledger_posting_amounts_valid(debit_amount, credit_amount) = 1) OR (currency IS NULL AND debit_amount = '0' AND credit_amount = '0' AND instrument_id IS NOT NULL AND quantity_delta IS NOT NULL AND ledger_quantity_nonzero_valid(quantity_delta) = 1) ) | etf_cockpit/data/local_storage.py |
| ledger_postings | <table constraint> | — | CHECK( (debit_amount = '0' AND credit_amount <> '0') OR (credit_amount = '0' AND debit_amount <> '0') ) | etf_cockpit/data/local_storage.py |
| ledger_postings | <table constraint> | — | CHECK( (instrument_id IS NULL AND quantity_delta IS NULL AND lot_id IS NULL) OR (instrument_id IS NOT NULL AND length(trim(instrument_id)) > 0 AND quantity_delta IS NOT NULL AND ledger_signed_decimal_valid(quantity_delta) = 1 AND (lot_id IS NULL OR length(trim(lot_id)) > 0)) ) | etf_cockpit/data/local_storage.py |
| ledger_postings | <table constraint> | — | CHECK(ledger_posting_amounts_valid(debit_amount, credit_amount) = 1) | etf_cockpit/data/local_storage.py |
| ledger_postings | <table constraint> | — | FOREIGN KEY(account_id, authority) REFERENCES ledger_accounts(account_id, authority) | etf_cockpit/data/local_storage.py |
| ledger_postings | <table constraint> | — | FOREIGN KEY(account_id, authority) REFERENCES ledger_accounts(account_id, authority) | etf_cockpit/data/local_storage.py |
| ledger_postings | <table constraint> | — | FOREIGN KEY(account_id, authority) REFERENCES ledger_accounts(account_id, authority) | etf_cockpit/data/local_storage.py |
| ledger_postings | <table constraint> | — | FOREIGN KEY(entry_id, authority) REFERENCES ledger_entries(entry_id, authority) | etf_cockpit/data/local_storage.py |
| ledger_postings | <table constraint> | — | FOREIGN KEY(entry_id, authority) REFERENCES ledger_entries(entry_id, authority) | etf_cockpit/data/local_storage.py |
| ledger_postings | <table constraint> | — | FOREIGN KEY(entry_id, authority) REFERENCES ledger_entries(entry_id, authority) | etf_cockpit/data/local_storage.py |
| ledger_postings | <table constraint> | — | PRIMARY KEY(entry_id, authority, line_number) | etf_cockpit/data/local_storage.py |
| ledger_postings | <table constraint> | — | PRIMARY KEY(entry_id, authority, line_number) | etf_cockpit/data/local_storage.py |
| ledger_postings | <table constraint> | — | PRIMARY KEY(entry_id, line_number) | etf_cockpit/data/local_storage.py |
| ledger_postings | account_id | TEXT | NOT NULL | etf_cockpit/data/local_storage.py |
| ledger_postings | account_id | TEXT | NOT NULL | etf_cockpit/data/local_storage.py |
| ledger_postings | account_id | TEXT | NOT NULL | etf_cockpit/data/local_storage.py |
| ledger_postings | authority | TEXT | NOT NULL CHECK(authority IN ('paper', 'broker')) | etf_cockpit/data/local_storage.py |
| ledger_postings | authority | TEXT | NOT NULL CHECK(authority IN ('paper', 'broker')) | etf_cockpit/data/local_storage.py |
| ledger_postings | authority | TEXT | NOT NULL CHECK(authority IN ('paper', 'broker')) | etf_cockpit/data/local_storage.py |
| ledger_postings | credit_amount | TEXT | NOT NULL | etf_cockpit/data/local_storage.py |
| ledger_postings | credit_amount | TEXT | NOT NULL CHECK(ledger_decimal_valid(credit_amount) = 1) | etf_cockpit/data/local_storage.py |
| ledger_postings | credit_amount | TEXT | NOT NULL CHECK(ledger_decimal_valid(credit_amount) = 1) | etf_cockpit/data/local_storage.py |
| ledger_postings | currency | TEXT | — | etf_cockpit/data/local_storage.py |
| ledger_postings | currency | TEXT | NOT NULL CHECK(currency GLOB '[A-Z][A-Z][A-Z]') | etf_cockpit/data/local_storage.py |
| ledger_postings | currency | TEXT | NOT NULL CHECK(currency GLOB '[A-Z][A-Z][A-Z]') | etf_cockpit/data/local_storage.py |
| ledger_postings | debit_amount | TEXT | NOT NULL | etf_cockpit/data/local_storage.py |
| ledger_postings | debit_amount | TEXT | NOT NULL CHECK(ledger_decimal_valid(debit_amount) = 1) | etf_cockpit/data/local_storage.py |
| ledger_postings | debit_amount | TEXT | NOT NULL CHECK(ledger_decimal_valid(debit_amount) = 1) | etf_cockpit/data/local_storage.py |
| ledger_postings | entry_id | TEXT | NOT NULL | etf_cockpit/data/local_storage.py |
| ledger_postings | entry_id | TEXT | NOT NULL | etf_cockpit/data/local_storage.py |
| ledger_postings | entry_id | TEXT | NOT NULL | etf_cockpit/data/local_storage.py |
| ledger_postings | instrument_id | TEXT | — | etf_cockpit/data/local_storage.py |
| ledger_postings | line_number | INTEGER | NOT NULL CHECK(line_number > 0) | etf_cockpit/data/local_storage.py |
| ledger_postings | line_number | INTEGER | NOT NULL CHECK(line_number > 0) | etf_cockpit/data/local_storage.py |
| ledger_postings | line_number | INTEGER | NOT NULL CHECK(line_number > 0) | etf_cockpit/data/local_storage.py |
| ledger_postings | lot_id | TEXT | — | etf_cockpit/data/local_storage.py |
| ledger_postings | quantity_delta | TEXT | — | etf_cockpit/data/local_storage.py |
| licensed_history | checksum | TEXT | NOT NULL | etf_cockpit/data/universe_membership.py |
| licensed_history | complete | INTEGER | NOT NULL | etf_cockpit/data/universe_membership.py |
| licensed_history | history_id | INTEGER | PRIMARY KEY AUTOINCREMENT | etf_cockpit/data/universe_membership.py |
| licensed_history | import_id | INTEGER | NOT NULL | etf_cockpit/data/universe_membership.py |
| licensed_history | instrument_id | TEXT | NOT NULL | etf_cockpit/data/universe_membership.py |
| licensed_history | interval_id | TEXT | NOT NULL | etf_cockpit/data/universe_membership.py |
| licensed_history | known_at | TEXT | NOT NULL | etf_cockpit/data/universe_membership.py |
| licensed_history | licence_ref | TEXT | NOT NULL | etf_cockpit/data/universe_membership.py |
| licensed_history | scope | TEXT | NOT NULL | etf_cockpit/data/universe_membership.py |
| licensed_history | snapshot_date | TEXT | NOT NULL | etf_cockpit/data/universe_membership.py |
| licensed_history | source | TEXT | NOT NULL CHECK(source='licensed') | etf_cockpit/data/universe_membership.py |
| licensed_history | source_id | TEXT | NOT NULL | etf_cockpit/data/universe_membership.py |
| licensed_history | valid_from | TEXT | NOT NULL | etf_cockpit/data/universe_membership.py |
| licensed_history | valid_to | TEXT | — | etf_cockpit/data/universe_membership.py |
| licensed_imports | checksum | TEXT | NOT NULL | etf_cockpit/data/universe_membership.py |
| licensed_imports | import_id | INTEGER | PRIMARY KEY AUTOINCREMENT | etf_cockpit/data/universe_membership.py |
| licensed_imports | imported_at | TEXT | NOT NULL | etf_cockpit/data/universe_membership.py |
| licensed_imports | licence_ref | TEXT | NOT NULL | etf_cockpit/data/universe_membership.py |
| licensed_imports | raw_path | TEXT | NOT NULL | etf_cockpit/data/universe_membership.py |
| licensed_imports | row_count | INTEGER | NOT NULL | etf_cockpit/data/universe_membership.py |
| licensed_imports | source_id | TEXT | NOT NULL | etf_cockpit/data/universe_membership.py |
| order_intents | account_id | TEXT | NOT NULL | etf_cockpit/trading/order_lifecycle.py |
| order_intents | created_at | TEXT | NOT NULL | etf_cockpit/trading/order_lifecycle.py |
| order_intents | currency | TEXT | NOT NULL | etf_cockpit/trading/order_lifecycle.py |
| order_intents | execution_allowed | INTEGER | NOT NULL DEFAULT 0 CHECK(execution_allowed = 0) | etf_cockpit/trading/order_lifecycle.py |
| order_intents | fee_estimate | TEXT | NOT NULL | etf_cockpit/trading/order_lifecycle.py |
| order_intents | idempotency_key | TEXT | NOT NULL UNIQUE | etf_cockpit/trading/order_lifecycle.py |
| order_intents | instrument_type | TEXT | — | etf_cockpit/trading/order_lifecycle.py |
| order_intents | limit_price | TEXT | NOT NULL | etf_cockpit/trading/order_lifecycle.py |
| order_intents | order_id | TEXT | PRIMARY KEY | etf_cockpit/trading/order_lifecycle.py |
| order_intents | quantity | TEXT | NOT NULL | etf_cockpit/trading/order_lifecycle.py |
| order_intents | remaining_quantity | TEXT | NOT NULL | etf_cockpit/trading/order_lifecycle.py |
| order_intents | settlement_date | TEXT | — | etf_cockpit/trading/order_lifecycle.py |
| order_intents | settlement_warning | TEXT | — | etf_cockpit/trading/order_lifecycle.py |
| order_intents | side | TEXT | NOT NULL CHECK(side IN ('buy', 'sell')) | etf_cockpit/trading/order_lifecycle.py |
| order_intents | state | TEXT | NOT NULL | etf_cockpit/trading/order_lifecycle.py |
| order_intents | venue | TEXT | — | etf_cockpit/trading/order_lifecycle.py |
| order_lifecycle_events | <table constraint> | — | FOREIGN KEY(order_id) REFERENCES order_intents(order_id) | etf_cockpit/trading/order_lifecycle.py |
| order_lifecycle_events | event_id | TEXT | NOT NULL UNIQUE | etf_cockpit/trading/order_lifecycle.py |
| order_lifecycle_events | event_type | TEXT | NOT NULL | etf_cockpit/trading/order_lifecycle.py |
| order_lifecycle_events | execution_allowed | INTEGER | NOT NULL DEFAULT 0 CHECK(execution_allowed = 0) | etf_cockpit/trading/order_lifecycle.py |
| order_lifecycle_events | occurred_at | TEXT | NOT NULL | etf_cockpit/trading/order_lifecycle.py |
| order_lifecycle_events | order_id | TEXT | NOT NULL | etf_cockpit/trading/order_lifecycle.py |
| order_lifecycle_events | payload_json | TEXT | NOT NULL | etf_cockpit/trading/order_lifecycle.py |
| order_lifecycle_events | prior_state | TEXT | NOT NULL | etf_cockpit/trading/order_lifecycle.py |
| order_lifecycle_events | sequence | INTEGER | PRIMARY KEY AUTOINCREMENT | etf_cockpit/trading/order_lifecycle.py |
| order_lifecycle_events | state | TEXT | NOT NULL | etf_cockpit/trading/order_lifecycle.py |
| order_reservations | <table constraint> | — | FOREIGN KEY(order_id) REFERENCES order_intents(order_id) | etf_cockpit/trading/cash_reservation.py |
| order_reservations | account_id | TEXT | NOT NULL | etf_cockpit/trading/cash_reservation.py |
| order_reservations | currency | TEXT | NOT NULL | etf_cockpit/trading/cash_reservation.py |
| order_reservations | fee_estimate | TEXT | NOT NULL | etf_cockpit/trading/cash_reservation.py |
| order_reservations | limit_price | TEXT | NOT NULL | etf_cockpit/trading/cash_reservation.py |
| order_reservations | order_id | TEXT | PRIMARY KEY | etf_cockpit/trading/cash_reservation.py |
| order_reservations | original_quantity | TEXT | NOT NULL | etf_cockpit/trading/cash_reservation.py |
| order_reservations | remaining_quantity | TEXT | NOT NULL | etf_cockpit/trading/cash_reservation.py |
| order_reservations | reserved_amount | TEXT | NOT NULL | etf_cockpit/trading/cash_reservation.py |
| order_reservations | status | TEXT | NOT NULL CHECK(status IN ('active', 'released')) | etf_cockpit/trading/cash_reservation.py |
| schema_migrations | applied_at | TEXT | NOT NULL | etf_cockpit/data/local_storage.py |
| schema_migrations | name | TEXT | NOT NULL | etf_cockpit/data/local_storage.py |
| schema_migrations | version | INTEGER | PRIMARY KEY | etf_cockpit/data/local_storage.py |
| storage_operations | completed_at | TEXT | NOT NULL | etf_cockpit/data/local_storage.py |
| storage_operations | detail_json | TEXT | NOT NULL | etf_cockpit/data/local_storage.py |
| storage_operations | operation | TEXT | NOT NULL | etf_cockpit/data/local_storage.py |
| storage_operations | operation_id | INTEGER | PRIMARY KEY AUTOINCREMENT | etf_cockpit/data/local_storage.py |
| transactional_records | <table constraint> | — | PRIMARY KEY(entity_type, entity_id) | etf_cockpit/data/local_storage.py |
| transactional_records | created_at | TEXT | NOT NULL | etf_cockpit/data/local_storage.py |
| transactional_records | deleted_at | TEXT | — | etf_cockpit/data/local_storage.py |
| transactional_records | entity_id | TEXT | NOT NULL | etf_cockpit/data/local_storage.py |
| transactional_records | entity_type | TEXT | NOT NULL | etf_cockpit/data/local_storage.py |
| transactional_records | payload_json | TEXT | NOT NULL | etf_cockpit/data/local_storage.py |
| transactional_records | revision | INTEGER | NOT NULL CHECK (revision > 0) | etf_cockpit/data/local_storage.py |
| transactional_records | updated_at | TEXT | NOT NULL | etf_cockpit/data/local_storage.py |
| unsettled_cash_commitments | <table constraint> | — | FOREIGN KEY(order_id) REFERENCES order_intents(order_id) | etf_cockpit/trading/cash_reservation.py |
| unsettled_cash_commitments | <table constraint> | — | PRIMARY KEY(order_id, fill_id) | etf_cockpit/trading/cash_reservation.py |
| unsettled_cash_commitments | account_id | TEXT | NOT NULL | etf_cockpit/trading/cash_reservation.py |
| unsettled_cash_commitments | buy_commitment | TEXT | NOT NULL | etf_cockpit/trading/cash_reservation.py |
| unsettled_cash_commitments | currency | TEXT | NOT NULL | etf_cockpit/trading/cash_reservation.py |
| unsettled_cash_commitments | fill_id | TEXT | NOT NULL | etf_cockpit/trading/cash_reservation.py |
| unsettled_cash_commitments | order_id | TEXT | NOT NULL | etf_cockpit/trading/cash_reservation.py |
| unsettled_cash_commitments | sale_credit | TEXT | NOT NULL | etf_cockpit/trading/cash_reservation.py |
| unsettled_cash_commitments | settlement_date | TEXT | — | etf_cockpit/trading/cash_reservation.py |
| workflow_runs | created_at | TEXT | NOT NULL | etf_cockpit/data/local_storage.py |
| workflow_runs | dedupe_key | TEXT | NOT NULL | etf_cockpit/data/local_storage.py |
| workflow_runs | error_fingerprint | TEXT | — | etf_cockpit/data/local_storage.py |
| workflow_runs | error_message | TEXT | NOT NULL DEFAULT '' | etf_cockpit/data/local_storage.py |
| workflow_runs | finished_at | TEXT | — | etf_cockpit/data/local_storage.py |
| workflow_runs | input_hash | TEXT | NOT NULL | etf_cockpit/data/local_storage.py |
| workflow_runs | inputs_json | TEXT | NOT NULL | etf_cockpit/data/local_storage.py |
| workflow_runs | label | TEXT | NOT NULL | etf_cockpit/data/local_storage.py |
| workflow_runs | outputs_json | TEXT | NOT NULL | etf_cockpit/data/local_storage.py |
| workflow_runs | resource_json | TEXT | NOT NULL | etf_cockpit/data/local_storage.py |
| workflow_runs | started_at | TEXT | — | etf_cockpit/data/local_storage.py |
| workflow_runs | status | TEXT | NOT NULL CHECK (status IN ('queued', 'running', 'succeeded', 'failed', 'cancelled', 'blocked')) | etf_cockpit/data/local_storage.py |
| workflow_runs | workflow_id | TEXT | PRIMARY KEY | etf_cockpit/data/local_storage.py |
| workflow_runs | workflow_type | TEXT | NOT NULL | etf_cockpit/data/local_storage.py |

## Application contracts

| Dataclass | Field | Annotation | First docstring line |
| --- | --- | --- | --- |
| — | — | — | — |

## Configuration files

| File | Top-level keys | Declared schema/version key |
| --- | --- | --- |
| configs/analysis_depth_profiles.yaml | profiles, reference_fixture_digest, reference_fixture_id, reference_machine, schema_version | schema_version="analysis-depth-profiles.v1" |
| configs/analysis_parity_v1.yaml | numeric_analysis_fields, numeric_tolerances, portfolio_artifacts, required_core_surfaces, schema_version, version | schema_version=1; version=analysis-parity-v1 |
| configs/audit_manifest.yaml | governance, required, version | version=1 |
| configs/authority_matrix.yaml | adr_id, adr_path, authority_stages, capabilities, completion_contract, executable_authority, execution_allowed, mandatory_core, optional_enrichment, policy_id, policy_version, schema_version | policy_version="2026-07-21"; schema_version="1.0" |
| configs/backtest_default.yaml | end_date, initial_value_eur, rebalance_frequency_days, start_date, strategies, transaction_cost_bps | — |
| configs/costs.yaml | base_currency, broker, cost_model, per_etf | — |
| configs/data_providers.yaml | providers | — |
| configs/data_source_policy.yaml | mandatory_tiers, policy_version, quota_failure, schema_version, sources | policy_version="2026-07-17"; schema_version="data-source-policy.v1" |
| configs/decision_cutover_v1.yaml | monitoring, rankers, replay, schema_version, validation, version | schema_version=1; version=decision-cutover-v1.0.0 |
| configs/decision_domains_v1.yaml | etf_decision_graph, hash_scheme, metrics, rank_cutover, schema_version, stock_decision, version | schema_version=1; version=decision-domains-v1.0.0 |
| configs/decision_opportunity_v1.yaml | labels, minimum_exposure_peer_sector_share, minimum_peer_support, minimum_universe_support, schema_version, timing, version | schema_version=1; version=opportunity-v1.0.0 |
| configs/etf_tax_assumptions_v1.yaml | hedge_enabled, hedge_ratio, hedge_target_currency, known_at, source_withholding_label, source_withholding_rate, tax_enabled, tax_residence_country, version | version=1 |
| configs/euronext_listing_v1.yaml | endpoint, markets, minimum_rows, provider_id, savings_bank_exclude_names, savings_bank_include_names, savings_bank_patterns, schema_version, scope, timeout_seconds, user_agent | schema_version=euronext-listing.v1 |
| configs/feature_registry.yaml | executable_authority, execution_allowed, features, policy_id, policy_version, schema_version | policy_version="2026-07-12"; schema_version="1.0" |
| configs/fixed_income_returns_v1.yaml | base_currency, bootstrap_samples, duration_buckets_years, horizon_days, maturity_buckets_years, maximum_observation_age_days, minimum_peer_support, ranking_seed, rate_shock_bps, risk_penalty_bps_per_duration_year, schema_version, spread_shock_bps, top_n | schema_version=1 |
| configs/fund_analysis_v1.yaml | annual_fee_day_count, dealing_cutoff_timezone, forecast, frequency_minimum_horizon_days, horizon_days, maximum_nav_anchor_gap_days, peers, reconciliation_tolerance, schema_version, screener, underlying_weight_tolerance | schema_version=1 |
| configs/gate_policy.yaml | executable_authority, execution_allowed, gates, policy_id, policy_version, schema_version | policy_version="2026-07-12"; schema_version="1.0" |
| configs/glossary.yaml | executable_authority, execution_allowed, glossary, policy_id, policy_version, schema_version | policy_version="2026-07-12"; schema_version="1.0" |
| configs/legal_terms_registry.yaml | code_and_packages, export_policy, jurisdictions, mandatory_model_ids, mandatory_source_ids, models, network_policy, professional_review_required, registry_version, review_status, schema_version, sources, terms_change_policy | registry_version="2026-07-17"; schema_version="legal-terms.v1" |
| configs/local_llm.yaml | api_key, base_url, enabled, max_tokens, model, timeout_seconds | — |
| configs/market_calendar_corrections.yaml | corrections, ledger_version, schema_version | ledger_version="2026-07-22"; schema_version=market-calendar-corrections.v1 |
| configs/model_settings.yaml | ensemble, forecast_horizons_trading_days, models | — |
| configs/mutation_thresholds_v1.yaml | critical_mutants, required_kill_rate, scope, version | version=1 |
| configs/performance_budgets.yaml | budgets, policy_version, regression_tolerance_pct, schema_version | policy_version="2026-07-17"; schema_version="performance-budgets.v1" |
| configs/plugin_registry.yaml | allowlist, execution_allowed, schema_version | schema_version="plugin-registry.v1" |
| configs/portfolio_forecast_v1.yaml | scenario_count, scenario_seed, schema_version, stress_correlation | schema_version=portfolio_forecast.v1 |
| configs/portfolio_targets.yaml | base_currency, cash_min_weight, cash_target_weight, portfolio, positions | — |
| configs/pre_trade_limits_v1.yaml | allowed_instruments, cancel_open_paper_orders_on_kill_switch, max_daily_turnover, max_order_value, max_override_ttl_seconds, max_position_exposure, schema_version | schema_version=pre_trade_limits.v1 |
| configs/product_governance.yaml | authority, default_portfolio_review_state, default_research_state, executable_authority, execution_allowed, policy_id, policy_version, product, prohibited_claims, required_disclosures, schema_version | policy_version="2026-07-12"; schema_version="1.0" |
| configs/rejection_registry.yaml | executable_authority, execution_allowed, last_reviewed, policy_version, registry_id, rejections, schema_version | policy_version=wave0-task4; schema_version="1.0" |
| configs/release_policy.yaml | artifact_roots, dependency_lock, mandatory, parser_dependency_lock, python_version, schema_version, signature_algorithm, signing_key_env | python_version="3.12.10"; schema_version="1.0" |
| configs/risk_limits.yaml | portfolio_limits, signal_limits | — |
| configs/risk_profiles_v1.yaml | default_profile_id, preset_version, profiles, schema_version | preset_version=1; schema_version=risk_profiles.v1 |
| configs/sample_calendar_identities.yaml | identities, schema_version | schema_version=sample-calendar-identities.v1 |
| configs/score_engine_v3.yaml | asset_policies, formula_version, horizons, schema_version | formula_version=score-engine-v3.0.0; schema_version=1 |
| configs/security_policy.yaml | credentials, network, parser_limits, schema_version, security_findings | schema_version="security-policy.v1" |
| configs/settings.yaml | controls, execution_allowed, revision, schema_version, semantic_version, settings_version | schema_version=settings_bundle.v1; semantic_version=1.0.0; settings_version=0 |
| configs/settlement_v1.yaml | settlement_lags | — |
| configs/sparebank_scorecard_v1.yaml | axes, formula_version, hard_gates, horizons, judgement, schema_version | formula_version=sparebank-scorecard-v1.0.0; schema_version=1 |
| configs/storage_policy.yaml | analytics, backups, encryption, exports, integrity, local_first, migrations, policy_id, recovery, retention, schema_version, storage_schema_version, transactional | schema_version=1; storage_schema_version=4 |
| configs/strategy_scope.yaml | capability_profiles, exclusion_policy, executable_authority, execution_allowed, instrument_rules, matrix_version, policy_id, policy_version, profile_assignments, schema_version, strategies, ui_surface | matrix_version="2026-07-21"; policy_version="2026-07-21"; schema_version="2.0" |
| configs/strategy_templates_v1.yaml | default_enabled, execution_allowed, registry_version, rejected_strategy_types, schema_version, templates | registry_version="strategy_templates.v1"; schema_version="1.0" |
| configs/supply_chain_intake.yaml | components, dependency_lock, policy, registry_version, review_status, schema_version, signature, third_party_notices | registry_version="2026-07-22"; schema_version="supply-chain-intake.v1" |
| configs/supply_chain_policy.yaml | approved_mitigations, critical_vulnerabilities, dependency_cooldown_days, dependency_lock, emergency_patch_window_hours, end_of_life_policy, missing_license_metadata, policy_version, schema_version, secret_scan, signature_algorithm, signing_key_env, unclassified_vulnerabilities, update_mode, vulnerability_tool | policy_version="2026-07-17"; schema_version="1.0" |
| configs/top_n_selection_v1.yaml | bootstrap_count, bootstrap_seed, maximum_top_n, minimum_effective_support, minimum_raw_support, schema_version, tie_break, top_n, utility_name, version, weights | schema_version=top_n_selection.v1; version=top_n_selection_v1 |
| configs/ui_acceptance.yaml | controls, version | version=3 |
| configs/ui_settings.yaml | default_etf, default_page, theme_mode, window_height, window_min_height, window_min_width, window_width | — |
| configs/universe.yaml | etfs, schema_version | schema_version=1 |
| configs/universe_membership_v1.yaml | allowed_scopes, configured_complete, configured_scope, configured_source_id, listing_complete, version | version=universe_membership_v1 |
