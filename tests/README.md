# Tests

Stdlib `unittest` (pytest is not installed in this environment). Run from the
repo root:

```
python3 -m unittest discover
```

`tests/__init__.py` puts `src/` on `sys.path` (the same bootstrap `verify.py`
uses), so `import rwoo...` works without installing the package.

The core/parser tests have no third-party dependency. The HTTP-API tests
(`test_api.py`, `test_payment.py`) exercise the ASP through Starlette's
`TestClient` and therefore require `fastapi` (pinned in `requirements.txt`).
They make **no network calls** — the market fetcher and evaluator are injected,
and the payment settlement is a stub verifier that cannot run in production.

## Coverage

- `test_parsers_economics.py` — Kalshi structured series (KXCPIYOY,
  KXECONSTATCPI, KXGDP, KXU3, KXPAYROLLS, KXFED) and Limitless free-text
  CPI/GDP/Fed titles: family/shape/status, month/quarter, and strike bins.
- `test_parsers_sports.py` — World Cup stage-of-elimination title shapes and
  the stage-text → stage-key mapping (Kalshi + Limitless).
- `test_parsers_weather.py` — Kalshi series → verified-station routing and
  target-date parsing, plus the free-text metric classifier.

These assert `parsers.py` behavior only; they make no network calls.
