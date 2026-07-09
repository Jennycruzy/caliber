# Opportunity Scan

- Created: 2026-07-09T19:14:36.771025+00:00
- Markets seen: 2170
- Markets evaluated: 156
- Markets included: 920
- Included unsupported: 764
- Markets skipped: 1250
- Actionable: 41
- Rule: YES if price < prob_low - costs; NO if price > prob_high + costs; otherwise no trade

| Rank | Status | Venue | Family | Market | Side | Oracle | Market | Net edge | Cost | Reason |
| ---: | --- | --- | --- | --- | --- | ---: | ---: | ---: | ---: | --- |
| 1 | actionable | kalshi | weather.temperature | Will the **high temp in Miami** be 92-93° on Jul 9, 2026? | NO | 0.1509 | 0.9550 | 0.7961 | 0.0080 | edge exceeds both the oracle's own uncertainty band and estimated trading friction |
| 2 | actionable | kalshi | weather.temperature | Will the **high temp in NYC** be <83° on Jul 9, 2026? | NO | 0.3284 | 0.9850 | 0.6506 | 0.0060 | edge exceeds both the oracle's own uncertainty band and estimated trading friction |
| 3 | actionable | kalshi | weather.temperature | Will the **high temp in LA** be 73-74° on Jul 9, 2026? | NO | 0.0264 | 0.5150 | 0.4661 | 0.0225 | edge exceeds both the oracle's own uncertainty band and estimated trading friction |
| 4 | actionable | kalshi | weather.temperature | Will the high temp in Chicago be 86-87° on Jul 9, 2026? | NO | 0.2417 | 0.7150 | 0.4540 | 0.0193 | edge exceeds both the oracle's own uncertainty band and estimated trading friction |
| 5 | actionable | kalshi | weather.temperature | Will the **high temp in LA** be 75-76° on Jul 9, 2026? | NO | 0.0416 | 0.4850 | 0.4209 | 0.0225 | edge exceeds both the oracle's own uncertainty band and estimated trading friction |
| 6 | actionable | kalshi | weather.temperature | Will the **high temp in LA** be 74-75° on Jul 10, 2026? | NO | 0.0166 | 0.4450 | 0.4061 | 0.0223 | edge exceeds both the oracle's own uncertainty band and estimated trading friction |
| 7 | actionable | kalshi | weather.temperature | Will the **high temp in Denver** be 88-89° on Jul 9, 2026? | NO | 0.0926 | 0.4300 | 0.3102 | 0.0272 | edge exceeds both the oracle's own uncertainty band and estimated trading friction |
| 8 | actionable | kalshi | weather.temperature | Will the **high temp in Denver** be >91° on Jul 9, 2026? | YES | 0.4207 | 0.1050 | 0.3042 | 0.0116 | edge exceeds both the oracle's own uncertainty band and estimated trading friction |
| 9 | actionable | kalshi | weather.temperature | Will the **high temp in Miami** be 93-94° on Jul 10, 2026? | NO | 0.0468 | 0.3550 | 0.2872 | 0.0210 | edge exceeds both the oracle's own uncertainty band and estimated trading friction |
| 10 | actionable | kalshi | weather.temperature | Will the **high temp in Miami** be <90° on Jul 9, 2026? | YES | 0.2743 | 0.0050 | 0.2639 | 0.0053 | edge exceeds both the oracle's own uncertainty band and estimated trading friction |
| 11 | actionable | kalshi | weather.temperature | Will the **high temp in Miami** be 91-92° on Jul 10, 2026? | NO | 0.2250 | 0.5050 | 0.2575 | 0.0225 | edge exceeds both the oracle's own uncertainty band and estimated trading friction |
| 12 | actionable | kalshi | weather.temperature | Will the **high temp in Miami** be 90-91° on Jul 9, 2026? | YES | 0.2523 | 0.0050 | 0.2420 | 0.0053 | edge exceeds both the oracle's own uncertainty band and estimated trading friction |
| 13 | actionable | kalshi | weather.temperature | Will the **high temp in NYC** be 83-84° on Jul 9, 2026? | YES | 0.2596 | 0.0150 | 0.2385 | 0.0060 | edge exceeds both the oracle's own uncertainty band and estimated trading friction |
| 14 | actionable | kalshi | weather.temperature | Will the **high temp in LA** be 76-77° on Jul 10, 2026? | NO | 0.0378 | 0.3000 | 0.2375 | 0.0247 | edge exceeds both the oracle's own uncertainty band and estimated trading friction |
| 15 | actionable | polymarket | sports.world_cup | Will France win the 2026 FIFA World Cup? | NO | 0.1255 | 0.3205 | 0.1945 | 0.0005 | edge exceeds both the oracle's own uncertainty band and estimated trading friction |
| 16 | actionable | kalshi | weather.temperature | Will the **high temp in Denver** be 90-91° on Jul 10, 2026? | NO | 0.1398 | 0.3350 | 0.1746 | 0.0206 | edge exceeds both the oracle's own uncertainty band and estimated trading friction |
| 17 | actionable | kalshi | weather.temperature | Will the high temp in Chicago be 83-84° on Jul 10, 2026? | NO | 0.0869 | 0.2750 | 0.1692 | 0.0190 | edge exceeds both the oracle's own uncertainty band and estimated trading friction |
| 18 | actionable | kalshi | weather.temperature | Will the high temp in Chicago be 81-82° on Jul 10, 2026? | NO | 0.2572 | 0.4500 | 0.1655 | 0.0273 | edge exceeds both the oracle's own uncertainty band and estimated trading friction |
| 19 | actionable | kalshi | weather.temperature | Will the **high temp in Miami** be 89-90° on Jul 10, 2026? | YES | 0.1951 | 0.0550 | 0.1315 | 0.0086 | edge exceeds both the oracle's own uncertainty band and estimated trading friction |
| 20 | actionable | kalshi | weather.temperature | Will the **high temp in Denver** be 90-91° on Jul 9, 2026? | NO | 0.2589 | 0.4450 | 0.1238 | 0.0623 | edge exceeds both the oracle's own uncertainty band and estimated trading friction |

## Included Unsupported

- limitless_sports_unknown_sports_parse_missing: 317
- limitless_sports.world_cup_prop_or_exact_outcome_model_missing: 142
- limitless_sports.esports_match_or_tournament_source_missing: 116
- limitless_economics.headline_cpi_monthly_bin_or_threshold_model_missing: 33
- limitless_sports.nhl_league_champion_model_missing: 32
- limitless_sports.nba_league_champion_model_missing: 30
- limitless_sports.tennis_tournament_winner_model_missing: 16
- limitless_economics.fed_rates_rate_decision_or_path_model_missing: 16
- limitless_sports.world_cup_stage_of_elimination_model_missing: 16
- polymarket_economics_not_supported: 14
- limitless_economics_unknown_economics_parse_missing: 9
- limitless_economics.gdp_quarterly_growth_bin_or_threshold_model_missing: 8

| Venue | Domain | Family | Shape | Market | Reason |
| --- | --- | --- | --- | --- | --- |
| kalshi | sports | sports | unknown_sports | no France wins the 1H by more than 1.5 goals,yes Morocco advances,yes Switzerland advances,yes England advances,yes Reg Time: Both Teams To Score,yes Reg Time: Both Teams To Score,yes Reg Time: Both Teams To Score,yes Reg Time: Both Teams To Score | included but not actionable: kalshi sports market included, but its rule has not been parsed into a known family |
| kalshi | sports | sports | unknown_sports | yes France wins the 1H by more than 1.5 goals,no Over 2.5 1H goals scored,yes France advances,no Goal Diff Reg Time: France wins by more than 2.5 goals | included but not actionable: kalshi sports market included, but its rule has not been parsed into a known family |
| kalshi | sports | sports | unknown_sports | no Morocco wins the 1H by more than 1.5 goals,yes Over 1.5 1H goals scored,no Goal Diff Reg Time: Switzerland wins by more than 1.5 goals,yes Reg Time: Over 2.5 goals scored | included but not actionable: kalshi sports market included, but its rule has not been parsed into a known family |
| kalshi | sports | sports | unknown_sports | yes France wins 1st Half,no Spain wins the 1H by more than 1.5 goals,yes Spain advances,yes Argentina advances,yes England advances,yes Reg Time: France,yes Kylian Mbappe: 1+,yes Lionel Messi: 1+,no Goal Diff Reg Time: France wins by more than 2.5 goals,no Goal Diff Reg Time: England wins by more than 1.5 goals | included but not actionable: kalshi sports market included, but its rule has not been parsed into a known family |
| kalshi | sports | sports | unknown_sports | no France wins the 1H by more than 1.5 goals,no Spain wins the 1H by more than 1.5 goals,no England wins the 1H by more than 1.5 goals,yes Morocco advances,yes Switzerland advances,yes Norway advances | included but not actionable: kalshi sports market included, but its rule has not been parsed into a known family |
| kalshi | sports | sports | unknown_sports | no France wins the 1H by more than 1.5 goals,yes France advances,yes 7+ corners,no Goal Diff Reg Time: France wins by more than 2.5 goals,yes France: 6+ | included but not actionable: kalshi sports market included, but its rule has not been parsed into a known family |
| kalshi | sports | sports | unknown_sports | yes France wins 1st Half,no Spain wins the 1H by more than 1.5 goals,yes Spain advances,yes Argentina advances,yes England advances,yes Reg Time: France,yes Kylian Mbappe: 1+,yes Lautaro Martinez: 1+,no Goal Diff Reg Time: France wins by more than 2.5 goals,no Goal Diff Reg Time: England wins by more than 1.5 goals | included but not actionable: kalshi sports market included, but its rule has not been parsed into a known family |
| polymarket | economics | economics.gdp | quarterly_growth_bin_or_threshold | US recession by end of 2026? | included but not actionable: polymarket GDP market included; GDP engine is not wired yet |
| polymarket | economics | economics.fed_rates | rate_decision_or_path | Will no Fed rate cuts happen in 2026? | included but not actionable: polymarket Fed-rate market included; Fed-rate engine is not wired yet |
| polymarket | economics | economics.fed_rates | rate_decision_or_path | Will 1 Fed rate cut happen in 2026? | included but not actionable: polymarket Fed-rate market included; Fed-rate engine is not wired yet |
| polymarket | economics | economics.fed_rates | rate_decision_or_path | Will 2 Fed rate cuts happen in 2026? | included but not actionable: polymarket Fed-rate market included; Fed-rate engine is not wired yet |
| polymarket | economics | economics.fed_rates | rate_decision_or_path | Will 3 Fed rate cuts happen in 2026? | included but not actionable: polymarket Fed-rate market included; Fed-rate engine is not wired yet |
| polymarket | economics | economics.fed_rates | rate_decision_or_path | Will 4 Fed rate cuts happen in 2026? | included but not actionable: polymarket Fed-rate market included; Fed-rate engine is not wired yet |
| polymarket | economics | economics.fed_rates | rate_decision_or_path | Will 5 Fed rate cuts happen in 2026? | included but not actionable: polymarket Fed-rate market included; Fed-rate engine is not wired yet |
| polymarket | economics | economics.fed_rates | rate_decision_or_path | Will 6 Fed rate cuts happen in 2026? | included but not actionable: polymarket Fed-rate market included; Fed-rate engine is not wired yet |
| polymarket | economics | economics.fed_rates | rate_decision_or_path | Will 7 Fed rate cuts happen in 2026? | included but not actionable: polymarket Fed-rate market included; Fed-rate engine is not wired yet |
| polymarket | economics | economics.fed_rates | rate_decision_or_path | Will 8 Fed rate cuts happen in 2026? | included but not actionable: polymarket Fed-rate market included; Fed-rate engine is not wired yet |
| polymarket | economics | economics.fed_rates | rate_decision_or_path | Will 9 Fed rate cuts happen in 2026? | included but not actionable: polymarket Fed-rate market included; Fed-rate engine is not wired yet |
| polymarket | economics | economics.fed_rates | rate_decision_or_path | Will 10 Fed rate cuts happen in 2026? | included but not actionable: polymarket Fed-rate market included; Fed-rate engine is not wired yet |
| polymarket | economics | economics.fed_rates | rate_decision_or_path | Will 11 Fed rate cuts happen in 2026? | included but not actionable: polymarket Fed-rate market included; Fed-rate engine is not wired yet |

## Skip Reasons

- kalshi_other_not_supported: 493
- polymarket_other_not_supported: 478
- limitless_other_domain_or_price_oracle_not_supported: 279
