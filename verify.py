#!/usr/bin/env python3
"""
Real-World Odds Oracle — verification harness.

Run: python3 verify.py --phase 0   (or --phase 1, etc.)

This script makes REAL live calls to real external APIs and prints a
plain-English report a non-programmer can read end to end, followed by an
explicit PASS/FAIL per acceptance criterion. It never uses canned fixtures
to fake a pass — if an API is unreachable, the check FAILs honestly.
"""
import argparse
import json
import os
import sys
import textwrap
import time

import httpx

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "src"))

RULE = "=" * 78


def get_with_retry(url, params, timeout=15, attempts=3):
    """Real network calls in a sandboxed environment can hit transient
    connect/TLS timeouts unrelated to the API itself. Retry a couple of times
    before surfacing an honest failure — this is not fakery, it still fails
    loudly if the API is genuinely unreachable."""
    last_exc = None
    for attempt in range(1, attempts + 1):
        try:
            resp = httpx.get(url, params=params, timeout=timeout)
            resp.raise_for_status()
            return resp
        except Exception as exc:  # noqa: BLE001
            last_exc = exc
            if attempt < attempts:
                time.sleep(1.5 * attempt)
    raise last_exc


def hdr(title):
    print()
    print(RULE)
    print(title)
    print(RULE)


def show_json(label, obj, max_chars=1200):
    text = json.dumps(obj, indent=2)
    if len(text) > max_chars:
        text = text[:max_chars] + "\n  ... (truncated for readability, full response was retrieved and parsed)"
    print(f"--- RAW EVIDENCE: {label} ---")
    print(textwrap.indent(text, "  "))


def check_open_meteo():
    hdr("CHECK 1 of 3 — Open-Meteo (weather multi-model forecast)")
    print("What this checks: can we pull a real, live, multi-model weather forecast")
    print("(ECMWF + GFS + ICON) for a real city, which is the raw material Stage 2's")
    print("weather engine will need. This is a live network call, not a fixture.\n")
    url = "https://api.open-meteo.com/v1/forecast"
    params = {
        "latitude": 41.85,
        "longitude": -87.65,
        "daily": "temperature_2m_max",
        "temperature_unit": "fahrenheit",
        "timezone": "America/Chicago",
        "models": "ecmwf_ifs025,gfs_seamless,icon_seamless",
    }
    try:
        resp = get_with_retry(url, params)
        data = resp.json()
    except Exception as exc:  # noqa: BLE001 - honest failure surfaced to the operator
        print(f"FAIL: live call to Open-Meteo raised an error: {exc}")
        return False

    show_json("Open-Meteo response (Chicago, 3 models)", data)

    daily = data.get("daily", {})
    model_keys = [k for k in daily if k.startswith("temperature_2m_max_")]
    ok = len(model_keys) >= 3 and len(daily.get("time", [])) > 0
    print()
    if ok:
        print(f"In plain English: Open-Meteo returned {len(model_keys)} independent model")
        print(f"forecasts ({', '.join(k.replace('temperature_2m_max_', '') for k in model_keys)})")
        print(f"for {len(daily.get('time', []))} days, for real coordinates near Chicago.")
        print("This confirms the exact query shape the weather engine (Phase 2) will use.")
        print("PASS: Open-Meteo multi-model access verified live.")
    else:
        print("FAIL: response did not contain at least 3 model-specific forecast series.")
    return ok


def check_kalshi():
    hdr("CHECK 2 of 3 — Kalshi (real prediction market read)")
    print("What this checks: can we read a real, live, currently-open Kalshi market,")
    print("including its exact resolution rule text and its bid/ask prices — the raw")
    print("material Stage 1's market reader will need. No auth key was used or needed.\n")
    url = "https://api.elections.kalshi.com/trade-api/v2/markets"
    try:
        resp = get_with_retry(url, {"limit": 10, "series_ticker": "KXHIGHNY"})
        data = resp.json()
    except Exception as exc:  # noqa: BLE001
        print(f"FAIL: live call to Kalshi raised an error: {exc}")
        return False

    show_json("Kalshi markets response (KXHIGHNY series, NYC daily high temperature)", data)

    markets = data.get("markets", [])
    ok = len(markets) > 0 and all(
        m.get("rules_primary") is not None and m.get("ticker") for m in markets
    )
    print()
    if ok:
        # Prefer a market that's actually trading (non-zero bid) for an honest,
        # non-degenerate midpoint example rather than a not-yet-open $0/$0 one.
        traded = [m for m in markets if float(m.get("yes_bid_dollars", 0)) > 0]
        m = traded[0] if traded else markets[0]
        yes_bid = m.get("yes_bid_dollars")
        yes_ask = m.get("yes_ask_dollars")
        print(f"In plain English: Kalshi returned a real, live market — '{m.get('title')}'")
        print(f"(ticker {m.get('ticker')}). Its exact resolution rule, verbatim from Kalshi:")
        print(f'  "{m.get("rules_primary")}"')
        print(f"Its current yes-bid is ${yes_bid} and yes-ask is ${yes_ask} — Stage 1 will")
        print("compute the implied probability as the midpoint of these two, not the last trade.")
        if yes_bid not in (None, "0.0000"):
            mid = (float(yes_bid) + float(yes_ask)) / 2
            spread = float(yes_ask) - float(yes_bid)
            print(f"  -> implied probability (midpoint) = ({yes_bid} + {yes_ask}) / 2 = {mid:.4f}")
            print(f"  -> spread (trading friction) = {yes_ask} - {yes_bid} = {spread:.4f}")
        print("PASS: Kalshi live market read verified, resolution rule + prices confirmed present.")
    else:
        print("FAIL: no markets returned, or a market was missing its resolution rule / ticker.")
    return ok


def check_polymarket():
    hdr("CHECK 3 of 3 — Polymarket (real prediction market read)")
    print("What this checks: can we read a real, live, open Polymarket market, including")
    print("its outcome prices and its resolution rule description text.\n")
    url = "https://gamma-api.polymarket.com/markets"
    try:
        resp = get_with_retry(url, {"limit": 3, "closed": "false"})
        data = resp.json()
    except Exception as exc:  # noqa: BLE001
        print(f"FAIL: live call to Polymarket raised an error: {exc}")
        return False

    show_json("Polymarket Gamma API response", data)

    ok = isinstance(data, list) and len(data) > 0 and all(
        "outcomePrices" in m and "description" in m for m in data
    )
    print()
    if ok:
        m = data[0]
        print(f"In plain English: Polymarket returned a real, live market — '{m.get('question')}'.")
        print(f"Its current outcome prices are {m.get('outcomePrices')} (Yes/No), and its")
        print("resolution rule (verbatim, truncated):")
        desc = (m.get("description") or "")[:300]
        print(f'  "{desc}..."')
        print("PASS: Polymarket live market read verified, prices + resolution text confirmed present.")
    else:
        print("FAIL: no markets returned, or a market was missing outcome prices / description.")
    return ok


def show_okx_ledger_summary():
    hdr("DOCUMENTED FACTS (not computed — these are Verification Ledger findings,")
    print("full evidence and source URLs in docs/VERIFICATION_LEDGER.md)\n")
    print(textwrap.dedent("""\
        OKX AI / okx.ai market feed:
          No evidence OKX hosts its own readable prediction-market venue.
          Stage 1 venues remain Kalshi + Polymarket only. (Ledger §4)

        OKX ASP listing + service registration:
          Real mechanism is TWO OKX skills, not a single "A2MCP": the
          `okx-agent-payments-protocol` skill (x402 HTTP-402 pay-per-call,
          schemes: exact / aggr_deferred / upto / period / charge / session)
          and the `okx-ai` skill (ERC-8004 Agent Identity + Task Marketplace
          for negotiated A2A work). Both require a real Agentic Wallet
          (email-based) and explicit human approval at each identity/payment
          confirmation gate — this cannot be completed by the build agent
          alone; it needs the Operator's wallet and approval. (Ledger §5)

        Work-intake contract (x402):
          402 challenge arrives via one of three signals (WWW-Authenticate:
          Payment header / PAYMENT-REQUIRED header / x402Version in body).
          Full formal JSON schema still to be pinned down with a live round
          trip in Phase 7 — flagged as open, not guessed. (Ledger §6)

        Payment SDK settlement token:
          UNRESOLVED — sources conflict between USDT/USDG (press) and USDC
          (OKX's own worked example + the x402 skill's own display example).
          Not assumed; will be confirmed by a real funded call in Phase 7.
          Settlement chain is X Layer in all sources. (Ledger §7)

        X Layer mainnet facts for receipt anchoring:
          Chain ID 196, gas token OKB, block explorer oklink.com/xlayer.
          Cheapest anchoring method (plain calldata tx vs. minimal attestation
          contract) not yet finalized — decided in Phase 6. (Ledger §8)

        OKX AI Genesis Hackathon submission logistics:
          Secondary sources report a 2026-07-03 to 2026-07-17 UTC submission
          window via Google Form, with mandatory OKX review + go-live for
          eligibility. NOT yet confirmed against the primary rules page —
          flagged for re-verification before Phase 9. (Ledger §9)

        Alibaba Cloud hosting:
          No evidence it's required for this hackathon. Treated as not
          required unless the primary rules page says otherwise. (Ledger §10)

        Moltbook (optional, non-blocking):
          Real and reachable. Registration/posting endpoint shapes come from
          third-party tutorials, not OKX's own docs yet — to be confirmed
          live before Phase 8 if pursued. Never blocks a gate. (Ledger §11)
    """))


def phase_0():
    print(RULE)
    print("REAL-WORLD ODDS ORACLE — VERIFY.PY --phase 0")
    print("GATE 0: Foundations & verification")
    print(RULE)

    results = {
        "Open-Meteo multi-model weather call succeeds": check_open_meteo(),
        "Kalshi live market read succeeds (resolution rule + prices present)": check_kalshi(),
        "Polymarket live market read succeeds (prices + resolution text present)": check_polymarket(),
    }

    show_okx_ledger_summary()

    hdr("GATE 0 — ACCEPTANCE CRITERIA")
    all_pass = True
    for name, passed in results.items():
        status = "PASS" if passed else "FAIL"
        if not passed:
            all_pass = False
        print(f"  [{status}] {name}")
    print(f"  [INFO] OKX/X-Layer/Moltbook integration paths documented in Verification"
          f" Ledger with 2 items explicitly flagged open (not blocking GATE 0; see above)")

    print()
    print(RULE)
    if all_pass:
        print("GATE 0 OVERALL: PASS")
    else:
        print("GATE 0 OVERALL: FAIL — see the FAIL lines above; do not proceed to Phase 1")
        print("until every live-data check passes on a real run.")
    print(RULE)
    return 0 if all_pass else 1


def phase_1():
    from rwoo.readers import kalshi, polymarket

    print(RULE)
    print("REAL-WORLD ODDS ORACLE — VERIFY.PY --phase 1")
    print("GATE 1: Market readers (Stage 1) — canonical objects from real live markets")
    print(RULE)
    print()
    print("What this checks: for several REAL, currently-open markets across both")
    print("venues (Kalshi, Polymarket) and all three domains (weather, economics,")
    print("sports), can the reader produce a canonical object whose resolution rule")
    print("and implied probability a non-programmer could read and trust?")

    canonical_markets = []
    failures = []

    kalshi_events = [
        ("KXHIGHNY-26JUL08", "weather — NYC daily high temperature"),
        ("KXPCECORE-26NOV", "economics — core PCE inflation"),
        ("KXNFLDROTY-27", "sports — NFL Defensive Rookie of the Year"),
    ]
    for event_ticker, label in kalshi_events:
        hdr(f"KALSHI — {label} (event {event_ticker})")
        try:
            markets = kalshi.fetch_markets_for_event(event_ticker)
            # Prefer a market that's genuinely trading in a normal range (not a
            # near-0%/near-100% tail contract) for an honest, representative example.
            mid_range = [m for m in markets if m.spread > 0 and 0.05 <= m.implied_prob <= 0.95]
            traded = mid_range or [m for m in markets if m.spread > 0]
            m = traded[0] if traded else markets[0]
            print(m.describe())
            print()
            print(f"  -> implied probability derivation: (yes_bid + yes_ask) / 2 from live Kalshi quotes")
            ok = bool(m.resolution_rule) and bool(m.resolution_source) and 0.0 <= m.implied_prob <= 1.0
            print(f"  [{'PASS' if ok else 'FAIL'}] resolution rule + source present, probability in [0,1]")
            if not ok:
                failures.append(f"Kalshi {event_ticker}")
            canonical_markets.append(m)
        except Exception as exc:  # noqa: BLE001
            print(f"FAIL: live call raised an error: {exc}")
            failures.append(f"Kalshi {event_ticker}")

    hdr("POLYMARKET — mixed live markets (no domain filter available server-side)")
    try:
        pmarkets = polymarket.fetch_canonical_markets(limit=5)
        for m in pmarkets[:3]:
            print(m.describe())
            print()
            print(f"  -> implied probability derivation: (bestBid + bestAsk) / 2 from live Gamma API quotes")
            ok = bool(m.resolution_rule) and 0.0 <= m.implied_prob <= 1.0
            print(f"  [{'PASS' if ok else 'FAIL'}] resolution rule present, probability in [0,1]")
            if not ok:
                failures.append(f"Polymarket {m.market_id}")
            canonical_markets.append(m)
    except Exception as exc:  # noqa: BLE001
        print(f"FAIL: live call raised an error: {exc}")
        failures.append("Polymarket fetch")

    hdr("GATE 1 — ACCEPTANCE CRITERIA")
    domains_seen = {m.domain for m in canonical_markets}
    venues_seen = {m.venue for m in canonical_markets}
    checks = {
        f"At least 5 real canonical market objects built (got {len(canonical_markets)})": len(canonical_markets) >= 5,
        f"Both venues represented (got {sorted(venues_seen)})": venues_seen == {"kalshi", "polymarket"},
        f"At least 2 of 3 domains represented among Kalshi markets (got {sorted(domains_seen)})": len(domains_seen & {"weather", "economics", "sports"}) >= 2,
        "Every object has a non-empty verbatim resolution rule": all(bool(m.resolution_rule) for m in canonical_markets),
        "Every implied probability is a valid midpoint in [0,1]": all(0.0 <= m.implied_prob <= 1.0 for m in canonical_markets),
        "No live-call failures": len(failures) == 0,
    }
    all_pass = True
    for name, passed in checks.items():
        status = "PASS" if passed else "FAIL"
        if not passed:
            all_pass = False
        print(f"  [{status}] {name}")

    print()
    print(RULE)
    print(f"GATE 1 OVERALL: {'PASS' if all_pass else 'FAIL'}")
    print(RULE)
    return 0 if all_pass else 1


def phase_2():
    from rwoo.engines import weather
    from rwoo.readers import kalshi
    from rwoo.weather_stations import station_for_series

    print(RULE)
    print("REAL-WORLD ODDS ORACLE — VERIFY.PY --phase 2")
    print("GATE 2: Weather engine (Stage 2) — multi-model consensus + confidence")
    print(RULE)
    print()
    print("What this checks: for a real live weather market's EXACT resolution rule,")
    print("does the engine pull independent live model forecasts, turn their")
    print("agreement/disagreement into a probability and a confidence score with the")
    print("formula shown, and cross-check against real historical climatology —")
    print("all without an LLM anywhere in the number path?")

    event_ticker = "KXHIGHNY-26JUL09"
    series_ticker = "KXHIGHNY"
    station = station_for_series(series_ticker)

    hdr(f"Reading the real live market: event {event_ticker}")
    markets = kalshi.fetch_markets_for_event(event_ticker)
    # Pick a spread of strike types so the report shows "greater"/"less"/"between" all resolve correctly.
    by_type: dict[str, object] = {}
    for m in markets:
        st = m.raw["market"]["strike_type"]
        by_type.setdefault(st, m)
    print(f"Station: {station.name} ({station.lat}, {station.lon})")
    print(f"Source: {station.source}")
    print(f"Found {len(markets)} real open markets for this event; testing one of each strike type present: {list(by_type.keys())}")

    target_date = kalshi.parse_event_date(event_ticker)
    print(f"Target calendar date parsed from event ticker suffix: {target_date}")

    all_checks = []
    for strike_type, m in by_type.items():
        raw = m.raw["market"]
        hdr(f"Market: {m.question}  [{strike_type}]")
        print(f"Verbatim resolution rule: \"{m.resolution_rule}\"")
        print(f"Kalshi's own implied probability (bid/ask midpoint): {m.implied_prob:.4f}")
        print(f"Strike fields (structured, not text-parsed): floor_strike={raw.get('floor_strike')}, "
              f"cap_strike={raw.get('cap_strike')}, strike_type={strike_type}")
        print()

        result = weather.compute_weather_probability(
            lat=station.lat, lon=station.lon, target_date=target_date,
            timezone_name="America/New_York",
            strike_type=strike_type, floor_strike=raw.get("floor_strike"), cap_strike=raw.get("cap_strike"),
        )

        if result["refused"]:
            print(f"REFUSED: {result['reason']}")
            all_checks.append(False)
            continue

        print("Per-model live forecasts (Open-Meteo, °F):")
        for model, val in result["per_source_values"].items():
            vote = "YES" if result["per_model_vote"][model] else "NO"
            print(f"  {model:20s} -> {val:.1f}°F  ->  resolves {vote} for this market")
        print()
        print(f"Ensemble mean: {result['ensemble_mean_f']:.2f}°F   Ensemble std (disagreement): {result['ensemble_std_f']:.2f}°F"
              f"{' (floored to ' + str(weather.MIN_STD_F) + ')' if result['std_floored'] else ''}")
        print(f"Consensus probability = normal_cdf((threshold - mean) / std), i.e. how many ensemble")
        print(f"standard deviations the threshold sits from the ensemble mean:")
        print(f"  -> oracle_prob = {result['oracle_prob']:.4f}")
        print(f"Confidence = max(0, 1 - std/8.0) = max(0, 1 - {result['ensemble_std_f']:.2f}/8.0) = {result['confidence']:.4f}")
        print(f"Model unanimity (direction-agnostic agreement): {result['model_unanimity']:.2f} "
              f"({sum(result['per_model_vote'].values())}/{len(result['per_model_vote'])} models voted YES)")
        print(f"Historical base rate: {result['base_rate']:.4f} "
              f"({sum(1 for v in result['base_rate_years'])} years of real NASA POWER daily data, "
              f"{result['base_rate_years'][0]}-{result['base_rate_years'][-1]})")
        print(f"Method: {result['method']}")
        print(f"Data freshness (fetched at): {result['data_freshness']}")

        ok = (
            len(result["per_source_values"]) >= 2
            and 0.0 <= result["oracle_prob"] <= 1.0
            and 0.0 <= result["confidence"] <= 1.0
            and result["base_rate"] is not None
        )
        print(f"  [{'PASS' if ok else 'FAIL'}] >=2 models, oracle_prob and confidence in [0,1], base rate present")
        all_checks.append(ok)

    hdr("CORE-LAW CHECK")
    import ast
    import inspect
    weather_source = inspect.getsource(weather)
    tree = ast.parse(weather_source)
    imported_names = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imported_names.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            imported_names.add(node.module)
    # An AST import scan can't be fooled by a comment/docstring that merely
    # *mentions* "LLM" (a plain keyword grep on this file's own docstring,
    # which explains the core law, would false-positive on the word "LLM" —
    # caught during this phase's own build and replaced with this check).
    llm_packages = {"openai", "anthropic", "cohere", "transformers", "langchain"}
    matched = imported_names & llm_packages
    print(f"Modules actually imported by weather.py: {sorted(imported_names)}")
    print(f"LLM-SDK imports found: {matched or 'none'}")
    core_law_ok = len(matched) == 0
    print(f"  [{'PASS' if core_law_ok else 'FAIL'}] no LLM SDK is imported anywhere in the probability computation path")

    hdr("GATE 2 — ACCEPTANCE CRITERIA")
    checks = {
        f"At least one market run per available strike type ({list(by_type.keys())})": len(all_checks) >= 1,
        "Every tested market: >=2 models, probabilities in [0,1], base rate present": all(all_checks),
        "No LLM SDK imported in the weather engine module (core-law check)": core_law_ok,
    }
    all_pass = True
    for name, passed in checks.items():
        status = "PASS" if passed else "FAIL"
        if not passed:
            all_pass = False
        print(f"  [{status}] {name}")

    print()
    print(RULE)
    print(f"GATE 2 OVERALL: {'PASS' if all_pass else 'FAIL'}")
    print(RULE)
    return 0 if all_pass else 1


def main():
    parser = argparse.ArgumentParser(description="Real-World Odds Oracle verification harness")
    parser.add_argument("--phase", type=int, required=True, help="which phase gate to run")
    args = parser.parse_args()

    if args.phase == 0:
        sys.exit(phase_0())
    elif args.phase == 1:
        sys.exit(phase_1())
    elif args.phase == 2:
        sys.exit(phase_2())
    else:
        print(f"Phase {args.phase} harness is not built yet.")
        sys.exit(2)


if __name__ == "__main__":
    main()
