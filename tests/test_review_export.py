import io
import zipfile

import pandas as pd

from stock_lab_core.backup import build_review_export_zip


def test_build_review_export_zip_includes_manifest_and_notes():
    payload = build_review_export_zip(
        {
            "today.csv": pd.DataFrame({"티커": ["AMD"], "판정": ["진입검토"]}),
            "bad/name?.csv": pd.DataFrame({"value": [1]}),
        },
        notes=[{"항목": "기준", "내용": "마스터표 기준"}],
    )

    with zipfile.ZipFile(io.BytesIO(payload)) as zf:
        names = set(zf.namelist())
        assert "today.csv" in names
        assert "name_.csv" in names
        assert "_notes.csv" in names
        assert "_manifest.csv" in names
        manifest = pd.read_csv(io.BytesIO(zf.read("_manifest.csv")))

    assert set(manifest["file"]) == {"today.csv", "name_.csv", "_notes.csv"}


def test_today_review_master_joins_holdings_and_money_flow(app_module):
    summary = pd.DataFrame([
        {
            "종목명": "Advanced Micro Devices",
            "티커": "AMD",
            "최종읽기": "✅정밀확인",
            "현재비중": 3.0,
            "목표비중": 6.0,
        }
    ])
    holdings = pd.DataFrame([
        {
            "자산명": "AMD 보유분",
            "티커": "AMD",
            "현재비중": 3.2,
            "목표비중": 6.0,
            "평가손익_원화": 12000,
        }
    ])
    flow = pd.DataFrame([
        {
            "Ticker": "AMD",
            "종목명": "Advanced Micro Devices",
            "후보군": "스윙후보",
            "판정": "진입검토",
            "타이밍": "눌림확인",
        }
    ])

    result = app_module.build_today_review_master_df(summary, holdings, flow)

    assert list(result["검토키"]) == ["amd"]
    assert result.loc[0, "보유_자산명"] == "AMD 보유분"
    assert result.loc[0, "돈흐름_후보군"] == "스윙후보"
    assert result.loc[0, "돈흐름_판정"] == "진입검토"


def test_today_review_master_does_not_duplicate_existing_money_flow_context(app_module):
    summary = pd.DataFrame([
        {
            "종목명": "Marvell Technology",
            "티커": "MRVL",
            "최종읽기": "⏳눌림대기",
            "돈흐름_후보군": "레이더 관찰",
            "돈흐름_판정": "관찰",
        }
    ])
    flow = pd.DataFrame([
        {
            "Ticker": "MRVL",
            "종목명": "마벨",
            "후보군": "스윙후보",
            "판정": "스윙 후보",
        }
    ])

    result = app_module.build_today_review_master_df(summary, pd.DataFrame(), flow)

    assert "돈흐름_후보군_x" not in result.columns
    assert "돈흐름_후보군_y" not in result.columns
    assert result.loc[0, "돈흐름_후보군"] == "레이더 관찰"


def test_sanitize_asset_name_recovers_new_money_flow_names(app_module):
    assert app_module.sanitize_asset_name("098120.KQ", "098120.KQ") == "마이크로컨텍솔"
    assert app_module.sanitize_asset_name("000500.KS", "000500.KS") == "가온전선"
    assert app_module.sanitize_asset_name("096770.KS", "096770.KS") == "SK이노베이션"
    assert app_module.sanitize_asset_name("AEHR", "AEHR") == "Aehr Test Systems"


def test_attach_today_flow_context_adds_money_flow_columns(app_module):
    summary = pd.DataFrame([
        {
            "종목명": "Lumentum",
            "티커": "LITE",
            "최종읽기": "✅정밀확인",
        }
    ])
    flow = pd.DataFrame([
        {
            "Ticker": "LITE",
            "종목명": "Lumentum",
            "후보군": "테마 주도주",
            "판정": "눌림대기",
            "시장맥락": "미국 · 포토닉스",
            "기준업종": "레이저/광원",
            "주의요인": "고점권",
        }
    ])

    result = app_module.attach_today_flow_context(summary, flow)

    assert result.loc[0, "돈흐름_후보군"] == "테마 주도주"
    assert result.loc[0, "돈흐름_판정"] == "눌림대기"
    assert result.loc[0, "돈흐름_기준업종"] == "레이저/광원"


def test_attach_today_flow_context_uses_theme_raw_context_when_not_shortlisted(app_module):
    summary = pd.DataFrame([
        {
            "종목명": "Marvell Technology",
            "티커": "MRVL",
            "최종읽기": "✅정밀확인",
        }
    ])
    snapshot = {
        "theme_flow_df": pd.DataFrame([
            {
                "Ticker": "MRVL",
                "종목명": "마벨",
                "시장": "미국",
                "테마": "포토닉스·광통신",
                "하위테마": "데이터센터 연결",
                "돈흐름점수": 12.4,
                "1개월수익률": 0.08,
                "가속도": 0.05,
                "가격수준": 0.72,
                "상태": "신규 유입",
            }
        ])
    }

    result = app_module.attach_today_flow_context(summary, pd.DataFrame(), snapshot=snapshot)

    assert result.loc[0, "돈흐름_후보군"] == "레이더 관찰"
    assert result.loc[0, "돈흐름_테마"] == "포토닉스·광통신"
    assert "돈흐름 12.4" in result.loc[0, "돈흐름_후보근거"]
    assert result.loc[0, "돈흐름_시장맥락"] != ""


def test_attach_today_flow_context_uses_etf_radar_context(app_module):
    summary = pd.DataFrame([
        {
            "종목명": "iShares Semiconductor ETF",
            "티커": "SOXX",
            "최종읽기": "⏳눌림대기",
        }
    ])
    snapshot = {
        "flow_df": pd.DataFrame([
            {
                "구분": "미국 섹터",
                "섹터": "반도체 iShares",
                "Ticker": "SOXX",
                "ETF 이름": "iShares Semiconductor ETF",
                "돈흐름점수": -5.0,
                "스윙점수": 4.0,
                "1개월수익률": 0.13,
                "가속도": -0.1,
                "가격수준": 0.78,
                "상태": "둔화 경고",
            }
        ])
    }

    result = app_module.attach_today_flow_context(summary, pd.DataFrame(), snapshot=snapshot)

    assert result.loc[0, "돈흐름_후보군"] == "ETF/섹터 레이더"
    assert "반도체" in result.loc[0, "돈흐름_시장맥락"]
    assert result.loc[0, "돈흐름_판정"] != ""


def test_today_analyst_target_summary_hides_noisy_internal_source(app_module):
    row = pd.Series({
        "유형": "주식",
        "애널목표가표시": "$293.88",
        "애널목표Upside": "+8.0%",
        "애널참여수": 43,
        "애널목표출처": "get_analyst_snapshot",
        "애널목표출처URL": "",
        "애널목표조회시각": "2026-10-06 04:34",
    })

    label = app_module.build_today_analyst_target_summary(row)

    assert label == "목표 $293.88 · Upside +8.0% · 43명"


def test_today_current_signal_audit_includes_every_signal(app_module):
    summary = pd.DataFrame([
        {
            "종목명": "Microsoft",
            "티커": "MSFT",
            "유형": "주식",
            "현재가": "$526.50",
            "최종읽기": "🚫추격금지",
            "🔥기술적 타점": "🚫하드차단: 볼린상단 이탈",
            "판정코드": "HARD_BLOCK_BOLLINGER_UPPER",
            "판정분류": "caution",
            "게이트상태": "대기/관찰",
            "돈흐름_판정": "추격금지",
        },
        {
            "종목명": "원익홀딩스",
            "티커": "030530.KQ",
            "유형": "주식",
            "현재가": "₩7,120",
            "최종읽기": "⏳눌림대기",
            "🔥기술적 타점": "✅스윙 후보: 정밀확인",
            "판정코드": "SWING_WATCH",
            "판정분류": "buyish",
            "게이트상태": "대기/관찰",
            "돈흐름_판정": "스윙 후보",
        },
    ])

    audit = app_module.build_today_current_signal_audit_df(summary)

    assert set(audit["티커"]) == {"MSFT", "030530.KQ"}
    assert "검증방향" in audit.columns
    assert "검증대상" in audit.columns
    assert audit.loc[audit["티커"] == "MSFT", "검증방향"].iloc[0] == "avoid"
    assert audit.loc[audit["티커"] == "030530.KQ", "검증방향"].iloc[0] == "buy"


def test_flow_auto_queue_prioritizes_swing_capture_before_high_chase(app_module, monkeypatch):
    flow = pd.DataFrame([
        {
            "Ticker": "HOT1.KQ",
            "종목명": "고점주1",
            "후보군": "테마 주도주 · 고점주의",
            "판정": "눌림대기",
            "타이밍": "급등 후 고점권 · 눌림대기",
            "돈흐름점수": 120.0,
            "등록상태": "미등록",
        },
        {
            "Ticker": "030530.KQ",
            "종목명": "원익홀딩스",
            "후보군": "스윙후보",
            "판정": "스윙 후보",
            "타이밍": "급등 포착",
            "돈흐름점수": 58.0,
            "등록상태": "미등록",
        },
    ])
    monkeypatch.setattr(app_module, "build_today_flow_shortlist_df", lambda snapshot=None: flow)

    items = app_module.build_today_flow_candidate_queue_items(snapshot={}, existing_items=(), limit=1)

    assert len(items) == 1
    assert items[0]["ticker"] == "030530.KQ"


def test_today_review_flags_detects_conflicting_weight_and_leverage_text(app_module):
    summary = pd.DataFrame([
        {
            "종목명": "Microsoft",
            "티커": "MSFT",
            "유형": "주식",
            "최종읽기": "✅정밀확인",
            "실행메모": "분할 매수",
            "🔥기술적 타점": "⚡레버리지 조건부 DCA",
            "📌후보등급": "A급",
            "현재비중": 7.0,
            "목표비중": 5.0,
        }
    ])

    flags = app_module.build_today_review_flags_df(summary)
    problems = " ".join(flags["문제"].astype(str).tolist())

    assert "비중초과와 매수형 문구" in problems
    assert "비레버리지 후보에 레버리지/DCA 문구" in problems


def test_today_review_flags_ignores_plain_defense_no_add_text(app_module):
    summary = pd.DataFrame([
        {
            "종목명": "NVIDIA",
            "티커": "NVDA",
            "유형": "주식",
            "최종읽기": "🚫추격금지",
            "실행메모": "추가매수 제외",
            "🔥기술적 타점": "🚫하드차단: 볼린상단 이탈",
            "📌후보등급": "🚫상단과열(추격금지)",
            "판정분류": "caution",
            "판정코드": "HARD_BLOCK_BOLLINGER_UPPER",
            "현재비중": 1.0,
            "목표비중": 5.0,
        }
    ])

    flags = app_module.build_today_review_flags_df(summary)
    problems = " ".join(flags["문제"].astype(str).tolist())

    assert "매수형 문구와 방어/차단 문구" not in problems


def test_today_review_flags_detects_low_rr_actionable_signal(app_module):
    summary = pd.DataFrame([
        {
            "종목명": "Recovery",
            "티커": "RCV",
            "유형": "주식",
            "최종읽기": "✅정밀확인",
            "실행메모": "분할 가능",
            "🔥기술적 타점": "✅우량주 회복 후보: 분할 검토",
            "📌후보등급": "✅우량주 회복후보",
            "판정분류": "buyish",
            "R/R": "0.42",
        }
    ])

    flags = app_module.build_today_review_flags_df(summary)
    problems = " ".join(flags["문제"].astype(str).tolist())

    assert "R/R 1 미만" in problems


def test_today_review_flags_use_gate_state_to_reduce_noisy_buyish_conflicts(app_module):
    summary = pd.DataFrame([
        {
            "종목명": "Weak RS Buyish",
            "티커": "WRB",
            "유형": "주식",
            "최종읽기": "✅정밀확인",
            "실행메모": "분할 가능",
            "🔥기술적 타점": "✅우량주 회복 후보: 분할 검토",
            "📌후보등급": "✅우량주 회복후보",
            "판정분류": "buyish",
            "게이트상태": "대기/관찰",
            "게이트근거": "섹터RS 약함",
        }
    ])

    flags = app_module.build_today_review_flags_df(summary)
    problems = " ".join(flags["문제"].astype(str).tolist())

    assert "buyish 원판정이 실행 게이트에서 낮아짐" in problems
    assert "매수형 문구와 방어/차단 문구" not in problems
