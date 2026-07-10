# Opportunity Scan

- Created: 2026-07-10T10:43:24.433516+00:00
- Markets seen: 5495
- Markets evaluated: 567
- Markets included: 1334
- Included unsupported: 767
- Markets skipped: 4161
- Actionable: 156
- Rule: YES if price < prob_low - costs; NO if price > prob_high + costs; otherwise no trade

| Rank | Status | Venue | Family | Market | Side | Oracle | Market | Net edge | Cost | Reason |
| ---: | --- | --- | --- | --- | --- | ---: | ---: | ---: | ---: | --- |
| 1 | actionable | kalshi | weather.temperature | Will the minimum temperature be <71° on Jul 10, 2026? | NO | 0.0024 | 0.9950 | 0.9873 | 0.0053 | edge exceeds both the oracle's own uncertainty band and estimated trading friction |
| 2 | actionable | polymarket | sports.world_cup | Will Europe (UEFA) win the 2026 FIFA World Cup? | NO | 0.0000 | 0.8250 | 0.8200 | 0.0050 | edge exceeds both the oracle's own uncertainty band and estimated trading friction |
| 3 | actionable | kalshi | weather.temperature | Will the minimum temperature be 73-74° on Jul 10, 2026? | NO | 0.1784 | 0.7850 | 0.5897 | 0.0168 | edge exceeds both the oracle's own uncertainty band and estimated trading friction |
| 4 | actionable | kalshi | weather.temperature | Will the minimum temperature be 73-74° on Jul 10, 2026? | NO | 0.1983 | 0.7450 | 0.5284 | 0.0183 | edge exceeds both the oracle's own uncertainty band and estimated trading friction |
| 5 | actionable | kalshi | weather.temperature | Will the maximum temperature be 92-93° on Jul 10, 2026? | NO | 0.0760 | 0.5850 | 0.4870 | 0.0220 | edge exceeds both the oracle's own uncertainty band and estimated trading friction |
| 6 | actionable | kalshi | weather.temperature | Will the minimum temperature be 54-55° on Jul 10, 2026? | NO | 0.1808 | 0.6650 | 0.4437 | 0.0406 | edge exceeds both the oracle's own uncertainty band and estimated trading friction |
| 7 | actionable | kalshi | weather.temperature | Will the maximum temperature be 111-112° on Jul 10, 2026? | NO | 0.2250 | 0.6700 | 0.4195 | 0.0255 | edge exceeds both the oracle's own uncertainty band and estimated trading friction |
| 8 | actionable | kalshi | weather.temperature | Will the minimum temperature be >81° on Jul 10, 2026? | YES | 0.4294 | 0.0050 | 0.4191 | 0.0053 | edge exceeds both the oracle's own uncertainty band and estimated trading friction |
| 9 | actionable | kalshi | weather.temperature | Will the **high temp in Miami** be 91-92° on Jul 10, 2026? | NO | 0.1784 | 0.6250 | 0.4151 | 0.0314 | edge exceeds both the oracle's own uncertainty band and estimated trading friction |
| 10 | actionable | kalshi | weather.temperature | Will the **high temp in LA** be 74-75° on Jul 10, 2026? | NO | 0.0298 | 0.4650 | 0.4128 | 0.0224 | edge exceeds both the oracle's own uncertainty band and estimated trading friction |
| 11 | actionable | limitless | economics.headline_cpi | June Inflation US - Annual - 3.8% | NO | 0.0348 | 0.4835 | 0.4066 | 0.0421 | edge exceeds both the oracle's own uncertainty band and estimated trading friction |
| 12 | actionable | kalshi | weather.temperature | Will the minimum temperature be 73-74° on Jul 10, 2026? | NO | 0.2374 | 0.6650 | 0.3970 | 0.0306 | edge exceeds both the oracle's own uncertainty band and estimated trading friction |
| 13 | actionable | kalshi | weather.temperature | Will the minimum temperature be 79-80° on Jul 10, 2026? | NO | 0.1077 | 0.5650 | 0.3951 | 0.0622 | edge exceeds both the oracle's own uncertainty band and estimated trading friction |
| 14 | actionable | kalshi | weather.temperature | Will the **high temp in Philadelphia** be 88-89° on Jul 10, 2026? | NO | 0.0869 | 0.4950 | 0.3856 | 0.0225 | edge exceeds both the oracle's own uncertainty band and estimated trading friction |
| 15 | actionable | kalshi | weather.temperature | Will the minimum temperature be 80-81° on Jul 10, 2026? | NO | 0.2581 | 0.6550 | 0.3461 | 0.0508 | edge exceeds both the oracle's own uncertainty band and estimated trading friction |
| 16 | actionable | kalshi | weather.temperature | Will the minimum temperature be 64-65° on Jul 10, 2026? | NO | 0.2589 | 0.7800 | 0.3391 | 0.1820 | edge exceeds both the oracle's own uncertainty band and estimated trading friction |
| 17 | actionable | kalshi | weather.temperature | Will the **high temp in Denver** be 90-91° on Jul 10, 2026? | NO | 0.1271 | 0.4750 | 0.3254 | 0.0225 | edge exceeds both the oracle's own uncertainty band and estimated trading friction |
| 18 | actionable | kalshi | weather.temperature | Will the maximum temperature be 111-112° on Jul 10, 2026? | NO | 0.1372 | 0.4850 | 0.3253 | 0.0225 | edge exceeds both the oracle's own uncertainty band and estimated trading friction |
| 19 | actionable | kalshi | weather.temperature | Will the maximum temperature be 92-93° on Jul 10, 2026? | NO | 0.1784 | 0.5250 | 0.3241 | 0.0225 | edge exceeds both the oracle's own uncertainty band and estimated trading friction |
| 20 | actionable | kalshi | economics.gdp | Will **real GDP** increase by more than 1.0% in Q2 2026? | NO | 0.5680 | 0.9100 | 0.3163 | 0.0257 | edge exceeds both the oracle's own uncertainty band and estimated trading friction |

## Included Unsupported

- limitless_sports_unknown_sports_parse_missing: 308
- limitless_sports.world_cup_prop_or_exact_outcome_model_missing: 132
- limitless_sports.esports_match_or_tournament_source_missing: 103
- polymarket_economics_not_supported: 48
- kalshi_sports_not_supported: 43
- limitless_sports.nhl_league_champion_model_missing: 32
- limitless_sports.nba_league_champion_model_missing: 30
- limitless_sports.tennis_tournament_winner_model_missing: 16
- limitless_economics.fed_rates_rate_decision_or_path_source_missing: 10
- limitless_economics_unknown_economics_parse_missing: 9
- limitless_economics.gdp_quarterly_growth_bin_or_threshold_model_missing: 8
- limitless_economics.headline_cpi_monthly_bin_or_threshold_model_missing: 7

| Venue | Domain | Family | Shape | Market | Reason |
| --- | --- | --- | --- | --- | --- |
| kalshi | sports | sports | unknown_sports | no Argentina wins the 1H by more than 1.5 goals,yes Spain advances,yes Argentina advances,yes Norway advances,no Reg Time: Over 2.5 goals scored | included but not actionable: kalshi sports market included, but its rule has not been parsed into a known family |
| kalshi | sports | sports | unknown_sports | yes Philadelphia,yes Houston,yes Bryce Harper: 1+,yes Alex Bregman: 1+,yes Hunter Brown: 4+,yes Chris Sale: 5+,yes Los Angeles D wins by over 1.5 runs,yes Over 6.5 runs scored,yes Over 5.5 runs scored,yes Over 3.5 runs scored,yes Over 4.5 runs scored,no Switzerland wins the 1H by more than 1.5 goals,yes Argentina advances,yes Reg Time: Over 1.5 goals scored,yes Over 144.5 points scored | included but not actionable: kalshi sports market included, but its rule has not been parsed into a known family |
| kalshi | sports | sports | unknown_sports | yes Philadelphia,yes Houston,yes Bryce Harper: 1+,yes Alex Bregman: 1+,yes Hunter Brown: 4+,yes Chris Sale: 5+,yes Los Angeles D wins by over 1.5 runs,yes Over 6.5 runs scored,yes Over 5.5 runs scored,yes Over 4.5 runs scored,no Switzerland wins the 1H by more than 1.5 goals,yes Argentina advances,yes Reg Time: Over 1.5 goals scored,yes Over 144.5 points scored | included but not actionable: kalshi sports market included, but its rule has not been parsed into a known family |
| kalshi | sports | sports | unknown_sports | no Spain wins the 1H by more than 1.5 goals,no Argentina wins the 1H by more than 1.5 goals,no England wins the 1H by more than 1.5 goals,yes Reg Time: Both Teams To Score,yes Lionel Messi: 1+,yes Erling Haaland: 1+ | included but not actionable: kalshi sports market included, but its rule has not been parsed into a known family |
| kalshi | sports | sports | unknown_sports | yes Belgium wins the 1H by more than 1.5 goals,yes Reg Time: Tie,yes Reg Time: Over 1.5 goals scored | included but not actionable: kalshi sports market included, but its rule has not been parsed into a known family |
| kalshi | sports | sports | unknown_sports | no Spain wins the 1H by more than 1.5 goals,no Argentina wins the 1H by more than 1.5 goals,no England wins the 1H by more than 1.5 goals,yes Reg Time: Both Teams To Score,yes Erling Haaland: 1+ | included but not actionable: kalshi sports market included, but its rule has not been parsed into a known family |
| kalshi | sports | sports | unknown_sports | yes Jannik Sinner,no Belgium wins the 1H by more than 1.5 goals,yes Reg Time: Spain | included but not actionable: kalshi sports market included, but its rule has not been parsed into a known family |
| kalshi | sports | sports | unknown_sports | no Spain wins the 1H by more than 1.5 goals,yes Argentina wins the 1H by more than 1.5 goals,yes England wins the 1H by more than 1.5 goals | included but not actionable: kalshi sports market included, but its rule has not been parsed into a known family |
| kalshi | sports | sports | unknown_sports | yes Belgium wins 1st Half,yes Argentina wins 1st Half,yes England wins 1st Half,no Argentina wins the 1H by more than 1.5 goals,no England wins the 1H by more than 1.5 goals,yes Over 0.5 1H goals scored,no Over 1.5 1H goals scored,yes Reg Time: Both Teams To Score,yes Reg Time: Belgium,yes Reg Time: Argentina,yes Reg Time: England,yes Reg Time: Over 2.5 goals scored,yes Reg Time: Over 2.5 goals scored | included but not actionable: kalshi sports market included, but its rule has not been parsed into a known family |
| kalshi | sports | sports | unknown_sports | no Spain wins the 1H by more than 1.5 goals,no Argentina wins the 1H by more than 1.5 goals,no England wins the 1H by more than 1.5 goals,yes Reg Time: Both Teams To Score | included but not actionable: kalshi sports market included, but its rule has not been parsed into a known family |
| kalshi | sports | sports | unknown_sports | yes Philadelphia,yes Houston,yes Bryce Harper: 1+,yes Hunter Brown: 4+,yes Chris Sale: 5+,yes Los Angeles D wins by over 1.5 runs,yes Over 6.5 runs scored,yes Over 5.5 runs scored,yes Over 4.5 runs scored,no Switzerland wins the 1H by more than 1.5 goals,yes Argentina advances,yes Reg Time: Over 1.5 goals scored,yes Over 144.5 points scored | included but not actionable: kalshi sports market included, but its rule has not been parsed into a known family |
| kalshi | sports | sports | unknown_sports | yes Belgium wins 1st Half,yes Argentina wins 1st Half,yes England wins 1st Half,no Argentina wins the 1H by more than 1.5 goals,no England wins the 1H by more than 1.5 goals,no Over 1.5 1H goals scored,yes Reg Time: Both Teams To Score,yes Reg Time: Belgium,yes Reg Time: Argentina,yes Reg Time: England,yes Reg Time: Over 2.5 goals scored,yes Reg Time: Over 2.5 goals scored | included but not actionable: kalshi sports market included, but its rule has not been parsed into a known family |
| kalshi | sports | sports | unknown_sports | yes Belgium wins the 1H by more than 1.5 goals,yes Reg Time: Tie,yes Reg Time: Over 2.5 goals scored | included but not actionable: kalshi sports market included, but its rule has not been parsed into a known family |
| kalshi | sports | sports | unknown_sports | no Argentina wins the 1H by more than 1.5 goals,yes Spain advances,yes Argentina advances,yes Norway advances,yes Lionel Messi: 1+,yes Harry Kane: 1+,yes Erling Haaland: 1+,no Reg Time: Over 5.5 goals scored,no Reg Time: Over 5.5 goals scored | included but not actionable: kalshi sports market included, but its rule has not been parsed into a known family |
| kalshi | sports | sports | unknown_sports | no England wins the 1H by more than 1.5 goals,yes Spain advances,yes Argentina advances,yes Norway advances,yes Lionel Messi: 1+,yes Harry Kane: 1+,yes Erling Haaland: 1+,no Reg Time: Over 5.5 goals scored,no Reg Time: Over 5.5 goals scored | included but not actionable: kalshi sports market included, but its rule has not been parsed into a known family |
| kalshi | sports | sports | unknown_sports | no Spain wins the 1H by more than 1.5 goals,yes Lamine Yamal: 1+,yes Belgium: 4+,yes Spain: 6+ | included but not actionable: kalshi sports market included, but its rule has not been parsed into a known family |
| kalshi | sports | sports | unknown_sports | yes Argentina wins 1st Half,yes England wins 1st Half,no Argentina wins the 1H by more than 1.5 goals,no England wins the 1H by more than 1.5 goals,no Over 1.5 1H goals scored,yes Reg Time: Both Teams To Score,yes Reg Time: Belgium,yes Reg Time: Argentina,yes Reg Time: England,yes Reg Time: Over 2.5 goals scored,yes Reg Time: Over 2.5 goals scored | included but not actionable: kalshi sports market included, but its rule has not been parsed into a known family |
| kalshi | sports | sports | unknown_sports | yes Philadelphia,yes Houston,yes Bryce Harper: 1+,yes Hunter Brown: 4+,yes Chris Sale: 5+,yes Los Angeles D wins by over 1.5 runs,yes Over 6.5 runs scored,yes Over 4.5 runs scored,no Switzerland wins the 1H by more than 1.5 goals,yes Argentina advances,yes Reg Time: Over 1.5 goals scored,yes Over 144.5 points scored | included but not actionable: kalshi sports market included, but its rule has not been parsed into a known family |
| kalshi | sports | sports | unknown_sports | yes Switzerland wins the 1H by more than 1.5 goals,yes Spain advances,yes Argentina advances,yes Norway advances,yes Lionel Messi: 1+,yes Harry Kane: 1+,yes Erling Haaland: 1+,no Reg Time: Over 5.5 goals scored,no Reg Time: Over 5.5 goals scored | included but not actionable: kalshi sports market included, but its rule has not been parsed into a known family |
| kalshi | sports | sports | unknown_sports | yes Alexander Zverev,yes Jannik Sinner,yes Jack Flaherty: 6+,yes Shota Imanaga: 6+,yes Nolan McLean: 6+,yes Sean Burke: 6+,yes Chris Sale: 6+,no Spain wins the 1H by more than 1.5 goals,yes Spain advances,yes Reg Time: Both Teams To Score,yes 11+ corners,yes Belgium: 4+,yes Spain: 6+,no Reg Time: Over 3.5 goals scored | included but not actionable: kalshi sports market included, but its rule has not been parsed into a known family |

## Skip Reasons

- kalshi_other_not_supported: 1959
- polymarket_other_not_supported: 1941
- limitless_other_domain_or_price_oracle_not_supported: 261
