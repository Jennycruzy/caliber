# Opportunity Scan

- Created: 2026-07-09T18:38:42.491823+00:00
- Markets seen: 571
- Markets evaluated: 156
- Markets skipped: 415
- Actionable: 43
- Rule: YES if price < prob_low - costs; NO if price > prob_high + costs; otherwise no trade

| Rank | Action | Venue | Market | Side | Oracle | Market | Net edge | Cost | Reason |
| ---: | --- | --- | --- | --- | ---: | ---: | ---: | ---: | --- |
| 1 | TRADE | kalshi | Will the **high temp in Miami** be 92-93° on Jul 9, 2026? | NO | 0.1578 | 0.9200 | 0.7470 | 0.0152 | edge exceeds both the oracle's own uncertainty band and estimated trading friction |
| 2 | TRADE | kalshi | Will the **high temp in NYC** be <83° on Jul 9, 2026? | NO | 0.3779 | 0.9750 | 0.5904 | 0.0067 | edge exceeds both the oracle's own uncertainty band and estimated trading friction |
| 3 | TRADE | kalshi | Will the **high temp in LA** be 75-76° on Jul 9, 2026? | NO | 0.0327 | 0.5050 | 0.4498 | 0.0225 | edge exceeds both the oracle's own uncertainty band and estimated trading friction |
| 4 | TRADE | kalshi | Will the **high temp in LA** be 73-74° on Jul 9, 2026? | NO | 0.0167 | 0.4600 | 0.4159 | 0.0274 | edge exceeds both the oracle's own uncertainty band and estimated trading friction |
| 5 | TRADE | kalshi | Will the **high temp in Denver** be 88-89° on Jul 9, 2026? | NO | 0.0841 | 0.5150 | 0.4084 | 0.0225 | edge exceeds both the oracle's own uncertainty band and estimated trading friction |
| 6 | TRADE | kalshi | Will the high temp in Chicago be 86-87° on Jul 9, 2026? | NO | 0.2277 | 0.6600 | 0.3966 | 0.0357 | edge exceeds both the oracle's own uncertainty band and estimated trading friction |
| 7 | TRADE | kalshi | Will the **high temp in LA** be 74-75° on Jul 10, 2026? | NO | 0.0166 | 0.4250 | 0.3663 | 0.0421 | edge exceeds both the oracle's own uncertainty band and estimated trading friction |
| 8 | TRADE | kalshi | Will the **high temp in LA** be 76-77° on Jul 10, 2026? | NO | 0.0378 | 0.3750 | 0.3158 | 0.0214 | edge exceeds both the oracle's own uncertainty band and estimated trading friction |
| 9 | TRADE | kalshi | Will the **high temp in Miami** be 93-94° on Jul 10, 2026? | NO | 0.0468 | 0.3550 | 0.2872 | 0.0210 | edge exceeds both the oracle's own uncertainty band and estimated trading friction |
| 10 | TRADE | kalshi | Will the **high temp in Miami** be 91-92° on Jul 10, 2026? | NO | 0.2250 | 0.5050 | 0.2575 | 0.0225 | edge exceeds both the oracle's own uncertainty band and estimated trading friction |
| 11 | TRADE | kalshi | Will the **high temp in Miami** be <90° on Jul 9, 2026? | YES | 0.2596 | 0.0050 | 0.2493 | 0.0053 | edge exceeds both the oracle's own uncertainty band and estimated trading friction |
| 12 | TRADE | kalshi | Will the **high temp in Miami** be 90-91° on Jul 9, 2026? | YES | 0.2492 | 0.0050 | 0.2389 | 0.0053 | edge exceeds both the oracle's own uncertainty band and estimated trading friction |
| 13 | TRADE | kalshi | Will the **high temp in NYC** be 83-84° on Jul 9, 2026? | YES | 0.2611 | 0.0250 | 0.2293 | 0.0067 | edge exceeds both the oracle's own uncertainty band and estimated trading friction |
| 14 | TRADE | polymarket | Will France win the 2026 FIFA World Cup? | NO | 0.1255 | 0.3185 | 0.1925 | 0.0005 | edge exceeds both the oracle's own uncertainty band and estimated trading friction |
| 15 | TRADE | kalshi | Will the high temp in Chicago be 81-82° on Jul 10, 2026? | NO | 0.2572 | 0.4450 | 0.1655 | 0.0223 | edge exceeds both the oracle's own uncertainty band and estimated trading friction |
| 16 | TRADE | kalshi | Will the **high temp in Denver** be 88-89° on Jul 10, 2026? | NO | 0.1757 | 0.3600 | 0.1582 | 0.0261 | edge exceeds both the oracle's own uncertainty band and estimated trading friction |
| 17 | TRADE | kalshi | Will the **high temp in Denver** be 90-91° on Jul 10, 2026? | NO | 0.1398 | 0.3200 | 0.1549 | 0.0252 | edge exceeds both the oracle's own uncertainty band and estimated trading friction |
| 18 | TRADE | kalshi | Will the high temp in Chicago be 83-84° on Jul 10, 2026? | NO | 0.0869 | 0.2600 | 0.1496 | 0.0235 | edge exceeds both the oracle's own uncertainty band and estimated trading friction |
| 19 | TRADE | kalshi | Will the **high temp in Miami** be 89-90° on Jul 10, 2026? | YES | 0.1951 | 0.0600 | 0.1212 | 0.0139 | edge exceeds both the oracle's own uncertainty band and estimated trading friction |
| 20 | TRADE | kalshi | Will the high temp in Chicago be 84-85° on Jul 9, 2026? | NO | 0.0487 | 0.1850 | 0.1208 | 0.0156 | edge exceeds both the oracle's own uncertainty band and estimated trading friction |

## Skip Reasons

- limitless_sports_shape_not_supported: 198
- polymarket_other_not_supported: 92
- limitless_other_domain_or_price_oracle_not_supported: 79
- limitless_economics_shape_not_supported: 37
- limitless_headline_cpi_not_supported_by_core_cpi_engine: 9
