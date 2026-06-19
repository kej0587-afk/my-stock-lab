from datetime import datetime

from stock_lab_core.market_memo import analyze_market_memo, build_auto_market_memo


def test_market_memo_links_semiconductor_watchlist_and_flags_sources():
    text = """
    🖥 반도체·AI
    • Micron(MU) HBM 서사 절정, 콜옵션 언급 급증
    • NVIDIA(NVDA) 200억 달러 규모 채권 발행 계획

    📉 매크로
    • 중국 5월 소매판매 YoY -0.6% 하락, 예상 미달
    """
    universe = [
        {"ticker": "NVDA", "name": "NVIDIA", "source": "관심", "asset_class": "us_stock_ai"},
        {"ticker": "SOXL", "name": "SOXL", "source": "보유", "asset_class": "us_etf_semiconductor"},
    ]

    result = analyze_market_memo(text, universe)

    assert result["has_content"] is True
    assert any(row["카테고리"] == "반도체/AI" for row in result["category_rows"])
    assert any(row["티커"] == "NVDA" and row["연결방식"] == "직접언급" for row in result["ticker_rows"])
    assert any(row["티커"] == "SOXL" and row["연결방식"] == "테마연결" for row in result["ticker_rows"])
    assert any("출처" in row["확인사유"] or "숫자" in row["확인사유"] for row in result["verification_flags"])


def test_market_memo_macro_negative_bias_is_detected():
    text = "• BOJ 기준금리 1.0%로 25bp 인상, 인플레이션 고점 지속"

    result = analyze_market_memo(text, [])

    macro = next(row for row in result["category_rows"] if row["카테고리"] in {"매크로", "외환/금리"})
    assert macro["점수"] < 0
    assert result["verification_flags"]


def test_market_memo_contextual_scoring_does_not_overrate_macro_energy_geopolitics():
    text = """
    📉 매크로
    • 영국 5월 핵심 소매판매 월간 1.2% 상승, 예측 0.3% 초과.
    • 독일 5월 생산자물가지수(PPI) 월간 0.3% 상승, 예측 0.7% 하회.
    • 일본 5월 CPI 1.5% 기록, 근원 CPI 1.4%로 예상과 일치, BOJ 금리인상 기조 유지.

    ⛽️ 에너지
    • 국제유가 주간 하락세 지속, WTI 배럴당 75~77달러 수준.
    • 러시아 국영 석유기업 로스네프트, OPEC+ 조건 하 생산량 확대 발표.

    🌍 지정학
    • 미국-이란 평화 합의 후 호르무즈 해협 선박 운항 재개, 원유 공급 기대감 상승.
    • EU, 러시아에 대한 부문별 제재 12개월 연장 발표.
    """

    result = analyze_market_memo(text, [])
    rows = {row["카테고리"]: row for row in result["category_rows"]}

    assert float(rows["매크로"]["점수"]) <= 1
    assert rows["매크로"]["톤"] != "호재 우위"
    assert float(rows["에너지"]["점수"]) <= 0
    assert rows["에너지"]["톤"] != "호재 우위"
    assert float(rows["지정학"]["점수"]) <= 0


def test_auto_market_memo_builds_newspick_style_draft():
    flow_snapshot = {
        "flow_df": [
            {
                "구분": "미국 섹터",
                "섹터": "반도체",
                "Ticker": "SOXX",
                "돈흐름점수": 24.5,
                "3개월수익률": 0.12,
                "가속도": 0.03,
                "상태": "주도",
            }
        ],
        "us_top5": [
            {
                "섹터": "반도체",
                "Ticker": "SOXX",
                "돈흐름점수": 24.5,
                "3개월수익률": 0.12,
                "가속도": 0.03,
                "상태": "주도",
            }
        ],
    }
    macro_data = {
        "10Y 금리": {"val": 4.3, "chg": -1.2, "icon": "🔻", "storm": False},
    }
    news_rows = [{"ticker": "NVDA", "name": "NVIDIA", "title": "NVIDIA AI 수요 강세", "sentiment": "호재"}]
    market_news_rows = [{"market_category": "지정학", "title": "Middle East ceasefire talks continue", "publisher": "Reuters"}]

    memo = build_auto_market_memo(
        flow_snapshot=flow_snapshot,
        macro_data=macro_data,
        market_news_rows=market_news_rows,
        news_rows=news_rows,
        now=datetime(2026, 6, 16, 15, 0),
    )

    assert "Stock Lab 자동 뉴스픽" in memo
    assert "핵심 해석" in memo
    assert "반도체·AI" in memo
    assert "SOXX" in memo
    assert "10Y 금리" in memo
    assert "1개월 -1.2%" in memo
    assert "시장 뉴스/서사" in memo
    assert "[지정학] Middle East ceasefire talks continue" in memo
    assert "NVIDIA AI 수요 강세" in memo


def test_auto_market_memo_builds_news_event_radar_from_rss_titles():
    market_news_rows = [
        {"market_category": "반도체·AI", "title": "Intel hires former SK hynix CEO Lee Seok-hee to lead foundry", "publisher": "Reuters"},
        {"market_category": "반도체·AI", "title": "SK하이닉스 주가 장중 7% 상승", "publisher": "연합뉴스"},
        {"market_category": "반도체·AI", "title": "Meta signs AI compute contract with data center firm Crusoe", "publisher": "Bloomberg"},
        {"market_category": "건설·인프라", "title": "현대로템, 모로코 철도 유지보수 사업 7,482억 원 규모 계약 수주", "publisher": "연합뉴스"},
        {"market_category": "암호화폐", "title": "Franklin Templeton files two Bitcoin reinvestment ETFs", "publisher": "CoinDesk"},
    ]

    memo = build_auto_market_memo(
        market_news_rows=market_news_rows,
        now=datetime(2026, 6, 19, 16, 0),
    )

    assert "뉴스 이벤트 레이더" in memo
    assert "▶️ 시황" in memo
    assert "▶️ 종목" in memo
    assert "Intel hires former SK hynix CEO" in memo
    assert "INTC" in memo
    assert "SK하이닉스(000660.KS)" in memo
    assert "Meta" in memo
    assert "현대로템(064350.KS)" in memo
    assert "Bitcoin(BTC)" in memo


def test_auto_market_memo_does_not_double_scale_macro_change():
    memo = build_auto_market_memo(
        macro_data={"10Y 금리": {"val": 4.49, "chg": -2.942, "icon": "🔻", "storm": False}},
        now=datetime(2026, 6, 16, 16, 0),
    )

    assert "1개월 -2.9%" in memo
    assert "-294.2%" not in memo


def test_auto_market_memo_prioritizes_short_rotation_over_hot_semis():
    flow_snapshot = {
        "flow_df": [
            {
                "구분": "미국 섹터",
                "섹터": "반도체 iShares",
                "Ticker": "SOXX",
                "돈흐름점수": 64.8,
                "3개월수익률": 0.738,
                "가속도": 0.603,
                "상태": "과열경보",
            },
            {
                "구분": "미국 섹터",
                "섹터": "기술",
                "Ticker": "XLK",
                "돈흐름점수": 42.0,
                "3개월수익률": 0.42,
                "가속도": 0.2,
                "상태": "강세",
            },
            {
                "구분": "미국 섹터",
                "섹터": "반도체 VanEck",
                "Ticker": "SMH",
                "돈흐름점수": 45.1,
                "3개월수익률": 0.56,
                "가속도": 0.444,
                "상태": "과열경보",
            },
        ],
        "us_top5": [
            {
                "섹터": "반도체 iShares",
                "Ticker": "SOXX",
                "돈흐름점수": 64.8,
                "3개월수익률": 0.738,
                "가속도": 0.603,
                "상태": "과열경보",
            }
        ],
    }
    index_rotation_rows = [
        {"지수/스타일": "나스닥100", "Ticker": "QQQ", "1D": -0.012, "5D": -0.018, "3M": 0.24, "판정": "단기 이탈"},
        {"지수/스타일": "반도체", "Ticker": "SOXX", "1D": -0.034, "5D": -0.052, "3M": 0.738, "판정": "장기주도/단기이탈"},
        {"지수/스타일": "다우존스", "Ticker": "DIA", "1D": 0.006, "5D": 0.012, "3M": 0.08, "판정": "순환 유입"},
        {"지수/스타일": "산업재", "Ticker": "XLI", "1D": 0.008, "5D": 0.014, "3M": 0.10, "판정": "순환 유입"},
    ]
    summary_rows = [
        {"종목명": "ProShares UltraPro QQQ", "티커": "TQQQ", "🔥기술적 타점": "눌림목 탑승"},
        {"종목명": "Microsoft", "티커": "MSFT", "🔥기술적 타점": "매수 관심"},
    ]

    memo = build_auto_market_memo(
        flow_snapshot=flow_snapshot,
        event_rows=[{"상태": "당일", "이벤트": "FOMC", "D-Day": "D-Day"}],
        index_rotation_rows=index_rotation_rows,
        summary_rows=summary_rows,
        now=datetime(2026, 6, 17, 11, 0),
    )

    assert "중기 돈흐름은 강하지만 1D 기준 단기 이탈" in memo
    assert "지수/스타일 로테이션" in memo
    assert "성장주보다 다우·산업재·금융·방어가 강합니다" in memo
    assert "레버리지 관찰 후보(추격 제외): ProShares UltraPro QQQ(TQQQ)" in memo
    assert "FOMC 전후에는 QQQ/TQQQ/QLD/SOXL" in memo


def test_market_memo_headline_prioritizes_rotation_and_event_caution():
    text = """
    • 반도체/AI는 강세 유지와 호재 수요 확대가 있지만 1D 기준 단기 이탈이 있습니다.
    • 단기 자금은 나스닥보다 다우·산업재·방어 쪽으로 로테이션됩니다.
    • FOMC 전후에는 TQQQ/QLD/SOXL 레버리지 추격 금지, 종가 확인 우선입니다.
    """

    result = analyze_market_memo(text, [])

    assert "단기 로테이션/이벤트 확인 필요" in result["headline"]
    assert result["action_bias"] == "레버리지 추격 금지 · 눌림/종가 확인 우선"
