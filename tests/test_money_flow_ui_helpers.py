import pandas as pd


def test_us_etf_composition_fallback_has_cibr_top5(app_module):
    comp_df, meta = app_module._composition_fallback_frame("CIBR")

    assert meta["name"] == "First Trust NASDAQ Cybersecurity ETF"
    assert comp_df["티커"].head(5).tolist() == ["CRWD", "FTNT", "PANW", "CSCO", "AVGO"]
    assert comp_df["비중(%)"].iloc[0] == 8.91


def test_us_etf_composition_reads_html_response(app_module, monkeypatch):
    class FakeResponse:
        text = """
        <table>
            <thead>
                <tr><th>Security Name</th><th>Identifier</th><th>Weighting</th></tr>
            </thead>
            <tbody>
                <tr><td>CrowdStrike Holdings</td><td>CRWD</td><td>8.91%</td></tr>
                <tr><td>Fortinet</td><td>FTNT</td><td>8.07%</td></tr>
            </tbody>
        </table>
        """

        def raise_for_status(self):
            return None

    if hasattr(app_module.fetch_us_etf_composition, "clear"):
        app_module.fetch_us_etf_composition.clear()
    monkeypatch.setattr(app_module.requests, "get", lambda *args, **kwargs: FakeResponse())

    comp_df, meta = app_module.fetch_us_etf_composition("CIBR")

    assert meta["fallback"] is False
    assert comp_df["티커"].tolist() == ["CRWD", "FTNT"]
    assert comp_df["비중(%)"].iloc[0] == 8.91


def test_cluster_list_prioritizes_current_timing_over_stale_strength(app_module, monkeypatch):
    monkeypatch.setattr(app_module, "_load_index_rotation_recent_returns", lambda ticker: {"1D": 0.0, "5D": 0.0})
    monkeypatch.setattr(
        app_module,
        "_get_market_cluster_snapshot_cached",
        lambda *args, **kwargs: {},
    )
    rotation_df = pd.DataFrame(
        [
            {
                "Ticker": "STRONG",
                "섹터": "중기강도",
                "RS(3M)": 0.30,
                "RS모멘텀": 0.25,
                "사분면": "주도",
                "1개월수익률": -0.06,
                "2주수익률": -0.04,
                "단기가속도": -0.03,
                "거래량증가": 0.2,
                "가격수준": 0.5,
            },
            {
                "Ticker": "READY",
                "섹터": "단기확인",
                "RS(3M)": 0.10,
                "RS모멘텀": 0.06,
                "사분면": "개선",
                "1개월수익률": 0.04,
                "2주수익률": 0.02,
                "단기가속도": 0.02,
                "거래량증가": 0.1,
                "가격수준": 0.6,
            },
        ]
    )
    clusters = {"오래강함": ["STRONG"], "지금확인": ["READY"]}

    result = app_module._build_cluster_list(rotation_df, clusters, market_context={}, market_key="미국")

    assert result[0]["name"] == "지금확인"
    assert result[0]["timing_state"] == "진입 가능"
    assert result[1]["timing_state"] == "하락 중"


def test_brief_leadership_uses_sector_ability_verdict_buckets(app_module):
    cards = [
        {
            "market": "한국",
            "title": "국내 AI 반도체·소부장",
            "action": "진입검토",
            "verdict": "진입검토·강도확인",
            "representatives": "마이크로컨텍솔",
            "values": {"강도": 4.8, "확산": 6.4, "단기유입": 8.0, "모멘텀": 8.2, "안정도": 5.2, "타점": 5.5},
            "total": 6.7,
            "short": 0.053,
            "mid": 0.206,
        },
        {
            "market": "한국",
            "title": "K뷰티·콘텐츠",
            "action": "추격금지",
            "verdict": "후행 강도·추격주의",
            "representatives": "코스맥스",
            "values": {"강도": 8.0, "확산": 4.5, "단기유입": 3.2, "모멘텀": 4.0, "안정도": 4.5, "타점": 2.8},
            "total": 7.3,
            "short": -0.011,
            "mid": -0.13,
        },
    ]

    leadership = app_module._brief_leadership_rows_from_sector_cards(cards, limit=3)

    assert leadership["leaders"][0]["name"].startswith("국내 AI 반도체")
    assert leadership["leaders"][0]["reading_label"].startswith("진입검토")
    assert leadership["lagging"][0]["name"].startswith("K뷰티")
    assert all(not row["name"].startswith("K뷰티") for row in leadership["leaders"])


def test_flow_action_normalizer_unifies_icon_and_text_labels(app_module):
    assert app_module.normalize_flow_action_label("✅ 진입검토") == "정밀관측"
    assert app_module.normalize_flow_action_label("✅ 정밀후보") == "정밀관측"
    assert app_module.normalize_flow_action_label("⏳ 눌림대기") == "눌림대기"
    assert app_module.normalize_flow_action_label("🚫 과열 추격금지") == "추격금지"
    assert app_module.normalize_flow_action_label("👀 반등확인") == "관심등록"
    assert app_module.normalize_flow_action_label("🔸 관망") == "관망/제외"

    assert app_module._flow_action_bucket("✅ 진입검토") == "정밀관측"
    assert app_module._flow_sector_action_rank("✅ 진입검토") == app_module.FLOW_ACTION_ORDER["정밀관측"]
    assert app_module._flow_sector_action_timing_score("✅ 진입검토") == 8.0
