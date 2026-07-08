# Build Gaps And Sequencing

Last updated: 2026-07-08

This file records incomplete work that must not be forgotten between phases.
It is intentionally blunt: if a component is not complete, it stays listed
until a verification gate proves otherwise.

## Sequencing Decision

Phase 6 is now **complete** (see below) — a real, correctly-verified X Layer
mainnet anchor exists. Next up: **Phase 7** (OKX.AI listing + service
registration + payment), since the real Agentic Wallet/Onchain OS skills are
already installed and working in this workspace. Economics/sports model
upgrades remain queued behind Phase 7+ — they don't block listing.

Recommended order (updated):

1. ~~Before Phase 6, clean up quick primary-source verification gaps~~ — done.
2. ~~Phase 6: receipts, append-only ledger, tamper evidence, X Layer anchoring~~ — done, including a corrected anchor after catching a false positive in the verifier (see docs/VERIFICATION_LEDGER.md §16.1).
3. **Phase 7 next:** OKX.AI ASP listing, service registration, Payment SDK, a real pay-per-call round trip.
4. Upgrade economics: verified consensus forecast source, no-lookahead backtest,
   calibration curve, Brier score.
5. Upgrade sports: simulator or multiple independent rating sources,
   no-lookahead backtest, calibration curve, Brier score.
6. Continue Phase 8+: daily proof loop, public pages.

## Immediate Checklist

Do before starting Phase 6:

- [x] Try to verify Kalshi's primary fee schedule directly.
- [x] Try to verify the primary OKX AI Genesis hackathon rules, deadline, and
      Google submission form.
- [x] Update `docs/VERIFICATION_LEDGER.md` with either successful primary
      evidence or a precise blocked/not-found finding.

Do in Phase 6:

- [x] Add append-only local calibration/receipt ledger.
- [x] Add receipt hash generation for verdict/calibration records.
- [x] Add hash-chain or equivalent tamper detection.
- [x] Add a tamper test to the verification harness.
- [x] Verify X Layer RPC path.
- [x] Verify the OKX Agentic Wallet transaction-signing flow for anchoring a
      real commitment on X Layer mainnet.
- [x] Anchor a real commitment on X Layer mainnet and print the
      transaction/explorer evidence.
- [x] Switch the local hash algorithm to real keccak256 (was sha3_256 — a
      different algorithm despite the similar name).
- [x] Fix a genuine false positive in the anchor verifier: this Agentic
      Wallet is an ERC-4337 smart account, so an outer bundler-transaction
      receipt status of "0x1" does NOT prove our inner UserOperation
      executed — it can succeed at the outer level while the inner call
      reverts. `verify_anchor_transaction()` now decodes the EntryPoint's
      `UserOperationEvent` and requires `success == true` explicitly. This
      caught and invalidated the first anchor attempt, which had silently
      reverted. See docs/VERIFICATION_LEDGER.md §16.1 for the full account.

Phase 6 status: **complete.** `python3 verify.py --phase 6` passes every
check, including a real, correctly-verified X Layer mainnet anchor
transaction (0x655d283549f0e809985a7fa401b1a8a14b6ad1419e3ebd15dd57424950c53ef2).
`data/anchors/phase6_anchor.json` and `data/receipts/phase6_anchor.jsonl` are
now tracked in git so any future drift between the anchored hash and the
ledger's actual content is visible in a diff, not silent.

## Gaps From Completed Phases Not Fully Covered By The Immediate Next Phase

### Production economics model and calibration

Current status: incomplete.

What exists: a conservative BLS-history baseline for core CPI markets.

Why incomplete: it is backward-looking official history, not a verified
forward-looking consensus forecast distribution. It is useful for a safe
baseline and for exercising the pipeline, but it is not yet "true odds" for a
future release.

Not covered by Phase 6: Phase 6 handles receipts and anchoring, not better
economic modeling.

Completion criteria:

- Verify a consensus forecast distribution source for CPI/PCE/NFP.
- Store raw pre-release forecast distributions with timestamps.
- Backtest with no lookahead against resolved historical releases/markets.
- Produce economics reliability curve and Brier score.
- Apply and document recalibration only if the backtest proves it is needed.

### Production sports model and calibration

Current status: incomplete.

What exists: a conservative World Cup baseline using live World Football Elo
ratings and two deterministic transforms.

Why incomplete: it is not a tournament simulator, does not model bracket path,
qualification state, injuries/lineups, or multiple independent rating systems.

Not covered by Phase 6: Phase 6 handles receipts and anchoring, not better
sports modeling.

Completion criteria:

- Add a proper simulator or multiple independent rating/projection sources.
- Verify all source timestamps and data availability.
- Backtest against resolved sports markets/events with no lookahead.
- Produce sports reliability curve and Brier score.
- Recalibrate if the backtest proves miscalibration.

### Primary Kalshi fee schedule PDF

Current status: incomplete primary-source verification.

What exists: fee formula corroborated by independent secondary sources and
Kalshi live API fields (`fee_type`, `fee_multiplier`).

Why incomplete: the primary PDF was blocked by a bot checkpoint when fetched.

Not covered by Phase 6 unless explicitly included.

Completion criteria:

- Retrieve/read the primary Kalshi fee schedule from Kalshi directly, or
  document a support-confirmed source.
- Update the Verification Ledger with the primary evidence.

### Primary hackathon rules and submission form

Current status: incomplete primary-source verification.

What exists: secondary-sourced deadline/submission information.

Why incomplete: the primary rules page/form must be checked before submission.

Not covered by Phase 6.

Completion criteria:

- Verify deadline, form URL, required assets, and eligibility criteria against
  primary OKX hackathon sources.
- Update the Verification Ledger.

### OKX payment settlement token

Current status: unresolved.

What exists: conflicting sources mention USDT/USDG/USDC on X Layer.

Why incomplete: only a real Payment SDK funded call can settle the discrepancy.

Not covered by Phase 6 unless payment work is pulled forward; normally covered
in Phase 7.

Completion criteria:

- Run a real funded OKX payment flow.
- Record actual settlement token and rail.
- Update service pricing accordingly.

### Public calibration page

Current status: not built.

What exists: Phase 5 computes weather calibration data in the harness.

Why incomplete: there is no live page reading from the same calibration store.

Not covered by Phase 6; covered later by Phase 8.5.

Completion criteria:

- Build a live public page from the calibration store.
- Show Brier score, reliability curve, call log, misses, and receipt hashes.
- Prove the page updates from data, not hardcoded HTML.
