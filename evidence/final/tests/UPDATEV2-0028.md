# UPDATEV2-0028 tests gate

Fresh focused command (exit 0):

`C:\Users\thor2\AppData\Local\Programs\Python\Python312\python.exe -m pytest tests/test_complete_audit_packet.py tests/test_backup_restore.py tests/test_import_export.py tests/test_data_health.py tests/test_release_hardening.py -q --tb=short`

The focused bundle passed at 100%. It covers complete audit-manifest validation, required-path rejection, backup/restore, import/export, Data Health, release hardening, unavailable providers, conflict export, holdings export and non-executable audit import. The authoritative full suite was rerun after the prior intermittent Windows transaction failure and passed at 100% (`pytest=0`; the complete output is preserved in `evidence/final/tests/UPDATEV2-0028-full-suite.txt`).
