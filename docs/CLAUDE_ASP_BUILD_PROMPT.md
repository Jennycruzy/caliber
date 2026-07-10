# REAL-WORLD ODDS ORACLE — CALLABLE ASP, PAID API, PUBLIC FRONTEND, DOMAIN, AND OKX.AI LISTING

This is one combined implementation specification. Read it completely before acting.

The domain, DNS, payment, security, and deployment sections have equal authority with the product requirements. Do not deploy, register the ASP, choose payment values, purchase anything, modify unrelated VPS services, or enable funded trading without the required operator approval.

You are extending the existing Real-World Odds Oracle repository. Do not restart, rename, replace, or weaken the deterministic forecasting engine.

Display name: **Real-World Odds Oracle**  
Code namespace: **rwoo**  
Tagline: **The true odds, proven.**

## Core positioning

Real-World Odds Oracle is a paid decision API for data-resolvable prediction markets. Agents and individuals call it for an independent deterministic probability, uncertainty interval, model version, source freshness, model-disagreement explanation, executable bid/ask comparison, estimated fees, net expected value, cross-venue comparison, calibration evidence, and tamper-evident receipt.

Execution is not the main product. Funded trading remains disabled until the relevant evidence gate passes. Do not implement authenticated order placement in this phase.

## Primary objective

Build a polished, production-ready ASP and public web experience around the existing deterministic core. Deliver:

1. Three callable paid oracle services.
2. Production HTTP API.
3. OKX Agent Payments Protocol-compatible HTTP 402 flow.
4. Public landing page.
5. Interactive API documentation.
6. Public calibration/evidence dashboard.
7. Receipt search and verification.
8. Health, readiness, status, and service metadata.
9. Security, observability, testing, and isolated deployment.
10. Dedicated branded domain and HTTPS.
11. End-to-end external paid-call verification.
12. Complete OKX.AI listing package.

## Product boundary

The product is: “A paid, evidence-backed decision oracle that tells agents what a prediction market is pricing, what the independent probability is, whether the difference survives uncertainty and costs, and why.”

The product is not a generic dashboard, an LLM guessing probabilities, a custodial betting service, an autonomous trading bot, a guaranteed-win product, a market-price republisher, or a service that calls every price difference arbitrage. No forecast is guaranteed to win.

## Preserve the Deterministic-Core Law

- Deterministic code produces every probability.
- An LLM may route and narrate but may not create, alter, veto, or sanity-check probabilities.
- Unsupported or ambiguous markets fail closed.
- Unknown entities must never silently become probability zero.
- Every result identifies its model version.
- Every successful or refused decision remains auditable.
- Model agreement is not automatically empirical calibration confidence.
- Missing data remains missing, not zero.
- Existing evidence and receipt ledgers remain append-only.

## Paid ASP services

Implement these identifiers unless current official OKX.AI registration rules require another format:

1. `rwoo.check_market`
2. `rwoo.cross_venue_edge`
3. `rwoo.get_calibration`

Verify allowed characters, dots versus underscores, length, descriptions, endpoint registration, schemas, and pricing requirements. If dots are prohibited use `rwoo_check_market`, `rwoo_cross_venue_edge`, and `rwoo_get_calibration`. Document the actual identifiers everywhere.

## Service 1 — Check Market

Endpoint: `POST /v1/check-market`

Purpose: read one supported market, invoke the correct deterministic engine, compute uncertainty and executable EV, attach calibration context and a receipt, and fail closed when unsafe to interpret.

Primary input:

```json
{
  "market": {
    "venue": "kalshi",
    "market_id": "KXHIGHNY-...",
    "question": "optional when market_id is supplied"
  },
  "include": {
    "why_trace": true,
    "calibration": true,
    "receipt": true
  }
}
```

Support `kalshi`, `polymarket`, and `limitless` unless another reader is explicitly added. A structured custom market may be accepted only when every required field is validated. Never fetch arbitrary user URLs or price free text when source, time, entity/location, strike, rule, or YES orientation cannot be bound.

Successful response:

```json
{
  "request_id": "req_...",
  "service": "rwoo.check_market",
  "status": "priced",
  "created_at": "...",
  "market": {
    "venue": "kalshi",
    "market_id": "...",
    "question": "...",
    "yes_subtitle": "...",
    "resolution_time": "...",
    "resolution_source": "...",
    "resolution_rule_hash": "..."
  },
  "forecast": {
    "event_group_id": "...",
    "domain": "weather",
    "family": "weather.temperature",
    "model_version": "weather-ensemble-v2",
    "oracle_probability": 0.71,
    "probability_interval": [0.64, 0.77],
    "confidence": 0.68,
    "model_agreement": {
      "available": true,
      "model_count": 3,
      "range": [0.66, 0.75],
      "median": 0.70,
      "largest_outlier": {"model": "gfs_seamless", "probability": 0.75}
    }
  },
  "market_comparison": {
    "market_probability": 0.53,
    "yes_bid": 0.51,
    "yes_ask": 0.55,
    "spread": 0.04,
    "side": "YES",
    "gross_edge": 0.18,
    "estimated_fees": 0.012,
    "expected_profit_per_contract": 0.148,
    "expected_return_on_cost": 0.269,
    "actionable": true,
    "reason": "..."
  },
  "why": {
    "summary": "...",
    "method": "...",
    "sources": [],
    "source_freshness": {},
    "model_probabilities": {},
    "limitations": []
  },
  "calibration": {
    "status": "accumulating",
    "scope": {
      "family": "weather.temperature",
      "model_version": "weather-ensemble-v2",
      "probability_band": "0.7-0.8"
    },
    "independent_resolved_events": 0,
    "next_checkpoint": 30,
    "promotion_eligible": false,
    "criteria": {}
  },
  "receipt": {
    "record_hash": "...",
    "chain_hash": "...",
    "sequence": 123,
    "verification_url": "..."
  }
}
```

Valid oracle refusals normally return HTTP 200 with `status: refused`, stable `reason_code`, explanation, missing capability, and receipt. Use HTTP 4xx for malformed requests, invalid schemas, unknown services, or authentication/payment errors.

## Service 2 — Cross-Venue Edge

Endpoint: `POST /v1/cross-venue-edge`

Input names left/right venue and market ID. Return original questions, normalized identity, rules, authorities, resolution times/timezones, YES orientation, cancellation differences, equivalence classification, executable asks, fees, entry cost, locked payout, net edge, risks, and receipt.

Classifications:

- `exact_equivalent`
- `candidate_needs_rule_review`
- `related_not_equivalent`
- `not_equivalent`

Only exact equivalence may be actionable. Never say risk-free. Use: “Complementary executable-price edge, subject to fill, custody, venue, cancellation, and settlement risk.”

## Service 3 — Get Calibration

Endpoints:

- `GET /v1/calibration`
- `GET /v1/calibration/{family}`
- `GET /v1/calibration/{family}/{model_version}`

Optional filters: probability band, venue, date range, limit, cursor. Return precommitted forecasts, resolved rows, independent groups, Brier score, reliability curve, maximum gap, version, domain/family, band results, official-source concordance, checkpoints, next checkpoint, eligibility, ledger verification, unresolved evidence, and sample warnings. Never show hit rate without independent sample count.

## Supporting endpoints

- `GET /healthz`
- `GET /readyz`
- `GET /version`
- `GET /v1/service-metadata`
- `GET /v1/supported-markets`
- `GET /v1/evidence/status`
- `GET /v1/receipts/{record_hash}`
- `GET /v1/receipts/{record_hash}/verify`
- `GET /openapi.json`
- `GET /docs`
- `GET /redoc`

Health must be cheap. Readiness checks engine import, ledger readability, required writable paths, and report integrity without depending on slow external APIs.

## HTTP API requirements

Use FastAPI/Pydantic unless an existing suitable standard exists. Require strict schemas, examples, request IDs in headers/body, stable JSON errors, body limits, request/upstream timeouts, bounded retries and concurrency, rate limits, no public stack traces, UTC, deterministic JSON, restricted CORS, trusted proxy settings, security headers, redacted logs, graceful shutdown, idempotency, and no secrets in code/logs/receipts/frontend.

Stable errors include: `INVALID_REQUEST`, `MARKET_NOT_FOUND`, `UNSUPPORTED_VENUE`, `UNSUPPORTED_MARKET`, `ENTITY_UNBOUND`, `YES_SIDE_UNBOUND`, `SOURCE_UNAVAILABLE`, `SOURCE_STALE`, `SOURCE_CONFLICT`, `MODEL_MISSING`, `FEE_UNKNOWN`, `RATE_LIMITED`, `PAYMENT_REQUIRED`, `PAYMENT_INVALID`, `PAYMENT_REPLAYED`, `UPSTREAM_TIMEOUT`, `INTERNAL_ERROR`.

## Payment architecture

Implement the seller using the current official **OKX Agent Payments Protocol** HTTP 402 flow. Do not call it A2MCP unless current official documentation requires that term.

At minimum support one-shot paid calls for check-market and cross-venue edge. Calibration summary may remain free; detailed slices may be paid after approval.

Requirements:

1. Unpaid protected requests return HTTP 402.
2. Preserve original body and input schema for replay.
3. Use protocol literals exactly: `x402Version`, `PAYMENT-REQUIRED`, `PAYMENT-SIGNATURE`, `X-PAYMENT` when needed, `WWW-Authenticate: Payment` when selected, and `PAYMENT-RESPONSE` when required.
4. Never invent proof formats.
5. Verify authorization server-side.
6. Reject expired, replayed, malformed, insufficient, wrong-token, wrong-chain, and wrong-recipient payments.
7. Bind payment to service, request, amount, recipient, and expiry.
8. Idempotent retry must not double-charge.
9. Never handle buyer private keys.
10. Never bypass buyer confirmation.
11. Link payment and decision receipt through request ID.
12. Configure prices; do not hardcode unverified assets.
13. Verify network, asset, decimals, recipient, and price live.
14. Development stubs must be impossible to enable accidentally in production.
15. Do not add subscriptions/channels unless required for listing.

Do not select prices, asset, network, or recipient without operator approval.

## Receipts and evidence

Every priced or refused decision creates a receipt committing request ID, service, request hash, market/event IDs, rule hash, model version, probability/refusal, interval, confidence, economics, why trace, calibration scope, source freshness, time, payment reference, previous hash, and chain hash. Never expose private payment data. A receipt may exist before the market resolves.

## Frontend objective

Build a clean, responsive financial-data site—not a casino, meme page, generic template, or fake trading dashboard. Use strong typography, whitespace, accessible contrast, restrained colors, responsive layout, keyboard access, and reduced-motion support. Avoid neon, spinning coins, fake charts, and guaranteed-win language.

## Landing page

Route `/`. Include:

1. Hero with product, tagline, concise paid-API description, Try API/View Calibration CTAs, live status, evidence-accumulating and execution-disabled badges.
2. Workflow: read rule, compute probability, compare price/cost, explain uncertainty, commit receipt, resolve/calibrate.
3. Three paid services with examples.
4. Real live example verdict—never hardcoded or fake.
5. Why-trace visualization with accessible table.
6. Calibration proof and honest empty state.
7. Cross-venue equivalence and risk disclosure.
8. Deterministic-Core Law.
9. Evidence/receipt/X Layer anchor explanation and verification.
10. Execution boundary: optional, gated, disabled, non-custodial.
11. Supported and deferred domains honestly.
12. Developer CTA.
13. Footer linking docs, status, calibration, receipts, methodology, limitations, license, contact, privacy/terms, and “Probabilities are estimates, not guarantees.”

## Public pages

- `/` landing
- `/docs` developer docs
- `/playground` schema-aware playground
- `/calibration` public evidence dashboard
- `/markets` coverage/current scan
- `/receipts` receipt verification
- `/methodology` method and limitations
- `/status` service/source/evidence status
- `/privacy`
- `/terms`

Calibration page shows timestamp, ledger validity, counts, independent groups, filters, Brier, gap, reliability, NOAA concordance, checkpoints, eligibility, insufficient-evidence state, successes and misses, downloadable JSON, and receipts. Missing values never become zero.

Docs cover discovery, payments, endpoints, schemas, refusals, errors, idempotency, rate limits, timeouts, evidence semantics, confidence vs agreement, receipts, coverage, versions, changelog, and limitations. Provide curl, Python, TypeScript, and agent JSON examples without exposing signatures.

Playground validates inputs and displays expected payment, result, why trace, and receipt. Never collect wallet private keys or invent a custom signing flow.

## Free versus paid

Free: landing, methodology, metadata, delayed/sample verdicts, high-level evidence, calibration summary, receipt verification, supported coverage, docs. Paid: fresh checks, fresh cross-venue comparisons, approved detailed calibration, high-frequency use. Do not publish the same fresh full result sold as paid.

Frontend/API must consume real `opportunity_scan_latest.json`, `calibration_report_latest.json`, evidence summaries, receipts, and metadata. Never hardcode metrics. Handle missing/stale reports, accumulating evidence, zero resolutions, source outage, empty cross-venue results, locked promotion, and unsupported families.

## Domain, DNS, and public URLs

A dedicated branded domain is required.

- `https://<DOMAIN>` public site
- `https://api.<DOMAIN>` API
- `https://api.<DOMAIN>/docs` API docs
- `https://api.<DOMAIN>/openapi.json` OpenAPI
- `https://<DOMAIN>/calibration`
- `https://<DOMAIN>/receipts`
- `https://<DOMAIN>/methodology`
- `https://<DOMAIN>/status`

Do not list a VPS IP, port 8088, localhost, another project’s DuckDNS, domain, or certificate.

Before deployment stop and request purchased domain, DNS access/provider, Cloudflare preference, and support email. Do not purchase or change DNS without approval.

Preferred DNS:

```text
A      @       38.49.216.59
A      api     38.49.216.59
CNAME  www     <DOMAIN>
```

If Cloudflare is used, start DNS-only; enable proxy only after verifying certificates and payment headers. Never cache paid responses or 402 challenges. Preserve payment, request-ID, idempotency, and settlement headers. Disable transformations that rewrite them.

## TLS and nginx

Issue separate valid root/API certificates, redirect HTTP to HTTPS, enable renewal, and pass renewal dry-run. Do not modify unrelated certificates. Bind API/frontend to localhost. Use isolated nginx blocks; preserve bodies/payment headers/request IDs; enforce body limits/timeouts; never cache paid responses/402 challenges; expose docs/OpenAPI but no admin routes. Do not alter unrelated domains.

Environment configuration:

```text
RWOO_PUBLIC_BASE_URL=https://<DOMAIN>
RWOO_API_BASE_URL=https://api.<DOMAIN>
RWOO_DOCS_URL=https://api.<DOMAIN>/docs
RWOO_CALIBRATION_URL=https://<DOMAIN>/calibration
RWOO_RECEIPTS_URL=https://<DOMAIN>/receipts
RWOO_SUPPORT_EMAIL=<operator supplied>
RWOO_ALLOWED_ORIGINS=https://<DOMAIN>
RWOO_TRUSTED_HOSTS=<DOMAIN>,api.<DOMAIN>
```

Do not hardcode the domain. Generate canonical URLs, OpenAPI servers, receipt links, sitemap, robots, and listing fields from configuration. Add titles, descriptions, canonical/Open Graph/X metadata, favicon/icons, sitemap, robots, and honest structured service data.

## Deployment

Replace the Python file server only after the new stack passes verification. Require dedicated HTTPS hostnames, isolated nginx, localhost processes, closed internal UFW ports, least-privilege systemd, root-owned source, rwoo-writable data/cache only, atomic deploy, timestamped rollback, health checks, log rotation, request limits, and no unrelated tenant/SSH/update/reboot/certificate changes without approval. Keep the old artifact endpoint until new site/API are proven.

## Testing

Add schema, refusal, unknown-entity, payment-required, invalid-payment, replay/idempotency, receipt-linkage, rate-limit, timeout, health/readiness, calibration-empty-state, accessibility, responsive, no-hardcoded-metric, external-client, HTTPS, nginx-payment-header, TLS-renewal, and unrelated-service tests. Prove unpaid → 402 → valid confirmed payment → 200 using the official supported mechanism. All existing 94 tests must pass.

## Security review

Prove no shell injection, SSRF, arbitrary URL fetch, traversal, ledger races/corruption, payment replay/double-charge, auth/private-key logging, stack traces, unrestricted CORS, unauthenticated admin, frontend secret leakage, LLM probability mutation, public internal ports, or cross-tenant changes.

## Operator inputs — do not guess

Stop for: dedicated domain, DNS access, payment recipient/wallet, approved network/asset, prices, support contact, privacy/terms identity, analytics preference, calibration free/paid policy, and human OKX registration confirmations.

## External acceptance

From outside the VPS prove root HTTPS, API metadata, health/readiness, OpenAPI/docs, correct unpaid 402, header preservation, confirmed real payment and settlement, linked receipt, no double-charge, closed internal ports, renewal dry-run, unrelated services healthy, and correct mobile pages.

Prepare listing URLs for website, API base, docs, calibration, receipts, status, and support. Do not submit until stable and externally tested.

## Deliverables

Return architecture, identifiers, routes, schemas, OpenAPI URL, payment design, page map, visual verification, files/config/env, tests, security review, deployment/public URLs, pending prices, listing fields, and blockers.

## Acceptance gate

Complete only when all tests pass; three services are callable/documented; unpaid protected calls return valid 402; paid replay returns 200; receipts link; frontend uses live data; empty calibration is honest; unknown entities fail closed; HTTPS works; internal ports are closed; no funded execution exists; and listing data is copy-ready.

## Implementation order

1. Inspect repository/deployment.
2. Confirm official OKX requirements.
3. Write schemas/tests.
4. Implement read-only endpoints.
5. Implement receipts/idempotency.
6. Implement payment challenge/verification.
7. Design/build frontend and shared system.
8. Build all public pages.
9. Connect live artifacts.
10. Run accessibility/security/tests.
11. Request operator inputs.
12. Configure domain/HTTPS.
13. Deploy with rollback.
14. Run external paid smoke test.
15. Prepare listing.
16. Do not implement funded trading.

At the end return GO, CONDITIONAL GO, or NO-GO for OKX.AI listing with exact remaining approvals. Begin by inspecting the existing repository and VPS. Preserve all evidence, receipts, tests, and deterministic behavior.
