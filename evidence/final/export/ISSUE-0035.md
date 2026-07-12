# ISSUE-0035 export gate

The fresh export command called `build_data_health` and `export_data_health`
with `as_of_date='2026-07-13'` and wrote
`evidence/final/export/ISSUE-0035-data-health.csv`. It reported `rows=12` and
the compatible header:

`dataset,status,path,row_count,checksum,as_of,freshness,provider,last_success,last_failure,warnings`

The CSV SHA-256 is
`bd89f6e01ea42e90d05a09675d881143f4584c3055e5dfcd7d9a7f7d124b4996`.
The UI export action writes the same schema to `data/derived/data_health.csv`
and displays the output path through the existing state message.
