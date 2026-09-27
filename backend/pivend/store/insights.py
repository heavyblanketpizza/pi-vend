"""Rule-based "next moves" from the dashboard numbers.

Deterministic on purpose: every insight states the numbers it is based on,
and carries a prompt the seller can hand to the agent to act on it.
"""

from __future__ import annotations

LEVEL_ORDER = {"critical": 0, "warning": 1, "good": 2, "info": 3}


def _won(n: int) -> str:
    return f"{n:,}원"


def build_insights(data: dict, limit: int = 5) -> list[dict]:
    out: list[dict] = []
    days = data["period"]["days"]
    kpis = {k["key"]: k for k in data["kpis"]}

    revenue = kpis["revenue"]
    if revenue["delta"] is not None and abs(revenue["delta"]) >= 10:
        up = revenue["delta"] > 0
        out.append({
            "level": "good" if up else "warning",
            "title": f"매출 {abs(revenue['delta']):.0f}% {'증가' if up else '감소'}",
            "body": f"최근 {days}일 매출 {_won(revenue['value'])} (직전 {days}일 {_won(revenue['prev'])}).",
            "prompt": f"최근 {days}일 매출이 직전 기간보다 {revenue['delta']:+.0f}% 변했어요. 상품별·키워드별로 원인을 분석하고 다음 액션을 제안해 주세요.",
        })

    movers = [p for p in data["products"] if p["delta"] is not None and p["revenue"] >= 100_000]
    if movers:
        worst = min(movers, key=lambda p: p["delta"])
        if worst["delta"] <= -15:
            out.append({
                "level": "warning",
                "title": f"{worst['name']} 매출 {abs(worst['delta']):.0f}% 감소",
                "body": f"최근 {days}일 {_won(worst['revenue'])}. 시즌 영향인지, 순위·가격 문제인지 점검이 필요해요.",
                "prompt": f"'{worst['name']}' 매출이 직전 기간보다 {abs(worst['delta']):.0f}% 줄었어요. 검색 트렌드와 경쟁 상품을 확인하고 상품명·가격·광고 중 무엇을 바꿔야 할지 제안해 주세요.",
            })
        best = max(movers, key=lambda p: p["delta"])
        if best["delta"] >= 25:
            out.append({
                "level": "good",
                "title": f"{best['name']} {best['delta']:.0f}% 성장",
                "body": f"최근 {days}일 {_won(best['revenue'])}. 재고와 광고 예산을 미리 챙기세요.",
                "prompt": f"'{best['name']}' 매출이 {best['delta']:.0f}% 늘었어요. 이 흐름을 키우려면 어떤 키워드와 광고를 늘리면 좋을지 알려 주세요.",
            })

    gaps = [k for k in data["keywords"] if k["market"] and k["market"] >= 3000 and (k["capture"] or 0) < 1]
    if gaps:
        gap = max(gaps, key=lambda k: k["market"])
        out.append({
            "level": "info",
            "title": f"‘{gap['keyword']}’ 수요 대비 유입이 적어요",
            "body": f"월 검색 {gap['market']:,}회 중 우리 스토어 유입은 {gap['capture']}%.",
            "prompt": f"'{gap['keyword']}'은 월 {gap['market']:,}회 검색되지만 우리 유입 점유율은 {gap['capture']}%예요. 상품명·태그 개선안과 광고 전략을 제안해 주세요.",
        })

    ads = data["ads"]
    if ads:
        losers = [k for k in ads["keywords"] if k["spend"] >= 50_000 and k["roas"] < 150]
        if losers:
            loser = max(losers, key=lambda k: k["spend"])
            out.append({
                "level": "critical",
                "title": f"광고 ‘{loser['keyword']}’ ROAS {loser['roas']}%",
                "body": f"광고비 {_won(loser['spend'])} 대비 전환매출 {_won(loser['revenue'])}. 입찰가나 소재를 조정하세요.",
                "prompt": f"광고 키워드 '{loser['keyword']}'가 광고비 {loser['spend']:,}원에 ROAS {loser['roas']}%예요. 입찰·키워드·상세페이지 중 무엇을 고칠지 분석해 주세요.",
            })

    conversion = kpis.get("conversion")
    if conversion and conversion["prev"] and conversion["delta"] <= -0.3:
        out.append({
            "level": "warning",
            "title": f"구매 전환율 {abs(conversion['delta']):.2f}%p 하락",
            "body": f"{conversion['prev']}% → {conversion['value']}%. 방문은 들어오는데 구매로 덜 이어져요.",
            "prompt": "구매 전환율이 떨어졌어요. 상세페이지와 가격 경쟁력을 점검하고 개선안을 제안해 주세요.",
        })

    week = [w for w in data["weekday"] if w["vs_avg"] is not None]
    if week:
        peak = max(week, key=lambda w: w["vs_avg"])
        if peak["vs_avg"] >= 12:
            out.append({
                "level": "info",
                "title": f"{peak['label']}요일 매출이 평균보다 {peak['vs_avg']:.0f}% 높아요",
                "body": "피크 요일 전날부터 광고 예산을 늘리면 효율이 좋아요.",
                "prompt": f"{peak['label']}요일 매출이 평균보다 {peak['vs_avg']:.0f}% 높아요. 요일별 광고 예산 배분안을 만들어 주세요.",
            })

    out.sort(key=lambda i: LEVEL_ORDER[i["level"]])
    return out[:limit]
