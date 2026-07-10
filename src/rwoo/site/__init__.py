"""Public web experience for the Real-World Odds Oracle.

A separate, read-only FastAPI app (from the paid API) that renders the public
site: landing, developer docs, playground, calibration/evidence dashboard,
coverage, receipt verification, methodology, status, privacy, and terms. Every
metric it shows is read at request time from the real published artifacts
(opportunity_scan_latest.json, calibration_report_latest.json) and the receipt
ledger — nothing is hardcoded, and missing data renders an honest empty state.
"""
