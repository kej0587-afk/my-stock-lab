"""Source-day eligibility for display-only sector observations; no I/O."""
from stock_lab_core.flow_snapshot import flow_source_date_rows


def sector_observation_basis(snapshot, dates):
    rows = flow_source_date_rows(snapshot)
    eligible = set()
    for market, key in (("한국", "KR"), ("미국", "US")):
        sources = [row for row in rows if row["시장"] == market]
        if sources and all(row["가격 기준일"] == (dates or {}).get(key)
                           and row["기준일 미확인"] == 0 for row in sources):
            eligible.add(market)
    leaders = {card["market"]: card["title"] for card in snapshot.get("sector_ability_cards", [])
               if card.get("rank") == 1 and card.get("market") in eligible}
    return rows, leaders
