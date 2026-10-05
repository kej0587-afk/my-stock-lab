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
