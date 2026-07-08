"""Deterministic domain routing — keyword/category rules, never an LLM.

This only sorts a market into weather/economics/sports/other so Stage 2 can
pick an engine; it is not a probability and has no bearing on the
Deterministic-Core Law either way, but it is kept rule-based for the same
reason everything else is: reproducibility. Given the same market object,
this function always returns the same domain.
"""

# Kalshi exposes an explicit, clean category string per event/series.
# Verified live 2026-07-08 (docs/VERIFICATION_LEDGER.md) against
# GET /trade-api/v2/series — the full real category list returned was:
# ['Climate and Weather', 'Commodities', 'Companies', 'Crypto', 'Economics',
#  'Education', 'Elections', 'Entertainment', 'Exotics', 'Financials',
#  'Health', 'Mentions', 'Politics', 'Science and Technology', 'Social',
#  'Sports', 'Transportation', 'World']
KALSHI_CATEGORY_MAP = {
    "Climate and Weather": "weather",
    "Economics": "economics",
    "Financials": "economics",
    "Commodities": "economics",
    "Sports": "sports",
}

_WEATHER_KEYWORDS = (
    "temperature", "high temp", "low temp", "rainfall", "rain", "snow",
    "snowfall", "hurricane", "storm", "wind speed", "heat wave", "weather",
)
_ECON_KEYWORDS = (
    "cpi", "inflation", "gdp", "unemployment", "jobs report", "nonfarm",
    "fed ", "federal reserve", "interest rate", "fomc", "recession",
)
_SPORTS_KEYWORDS = (
    "vs.", "vs ", "wins the", "championship", "playoff", "world cup",
    "super bowl", "nba", "nfl", "mlb", "nhl", "ncaa",
)


def classify_kalshi(category: str | None, question: str) -> str:
    if category and category in KALSHI_CATEGORY_MAP:
        return KALSHI_CATEGORY_MAP[category]
    return _classify_by_keywords(question)


def classify_polymarket(tag_labels: list[str], question: str) -> str:
    lowered = {t.lower() for t in tag_labels}
    if lowered & {"weather", "climate"}:
        return "weather"
    if lowered & {"economy", "economics", "finance", "fed", "inflation"}:
        return "economics"
    if lowered & {"sports", "nba", "nfl", "mlb", "nhl", "soccer", "football"}:
        return "sports"
    return _classify_by_keywords(question)


def _classify_by_keywords(question: str) -> str:
    q = question.lower()
    if any(kw in q for kw in _WEATHER_KEYWORDS):
        return "weather"
    if any(kw in q for kw in _ECON_KEYWORDS):
        return "economics"
    if any(kw in q for kw in _SPORTS_KEYWORDS):
        return "sports"
    return "other"
