"""Read-only report extension, isolated from signal grades and market gates."""

from stock_lab_core.report_build import register_loaded_source
from stock_lab_core.report_evidence import _cell, first, number, records, text
from stock_lab_core.market_observation import (
    build_sector_rotation, build_event_study, tag_candidate_news, build_observation_hypotheses,
)
from stock_lab_core.market_sentiment import sentiment_evidence

register_loaded_source(__name__, __file__)

# Display mapping only. A keyword match is not a confirmed event or trade signal.
CATALYST_EXPOSURES = {
    "000660.KS": ("SK하이닉스", "SK hynix"), "005930.KS": ("삼성전자", "Samsung Electronics"),
    "NVDA": ("엔비디아", "NVIDIA"), "GOOGL": ("알파벳", "Alphabet", "Google"),
    "META": ("메타", "Meta"), "MSFT": ("마이크로소프트", "Microsoft"),
    "396500.KS": ("반도체", "삼전닉스", "semiconductor"),
    "0167A0.KS": ("반도체", "삼전닉스", "semiconductor"),
    "SOXX": ("반도체", "semiconductor"), "RAM": ("DRAM", "메모리"),
}


def _pct(value):
    return f"{value * 100:+.2f}%" if number(value) is not None else "미연결"


def observation_report_lines(context, summary_rows, news, now):
    sentiment = sentiment_evidence(context)
    rotation = build_sector_rotation(context.get("price_frames", {}), context.get("closed_flow_rows", []),
                                     sessions=context.get("sessions", {}), as_of=now)
    candidates = tag_candidate_news(news, entity_keywords=CATALYST_EXPOSURES)
    study = build_event_study(context.get("confirmed_historical_events", []), context.get("price_frames", {}),
                             as_of=now, window=5, session_schedules=context.get("event_session_schedules", {}))
    hypotheses = build_observation_hypotheses(rotation, study, candidates)
    lines = ["", "## 관찰 근거 · 매매 판정과 별도", "**투자심리 상태**", sentiment["state"],
             "지표 | 관측 | 기준일 | 범위·한계", "--- | --- | --- | ---"]
    lines += [" | ".join(_cell(r[k]) for k in ("지표", "관측", "기준일", "범위·한계")) for r in sentiment["rows"]]
    lines += ["", "**로테이션 관찰 후보**",
              "동일 시장·확정 거래일 기준. 상·하위는 20일 상대강도 변화순, 개선 소외는 20일 음수·5일 양수 중 5일 상대강도순입니다. 돈흐름은 실제 자금 유입액이 아닌 기존 가격·거래량 점수이며 순위를 매수 순서로 쓰지 않습니다.",
              "시장·분류 | ETF·벤치 | 기준일 | RS 5D / 20D | 3M 가속도(%p) | 돈흐름점수", "--- | --- | --- | --- | --- | ---"]
    rotation_count = 0
    for market, result in rotation.get("markets", {}).items():
        for key, label in (("top3", "상위"), ("bottom3", "하위"), ("improving_laggards3", "개선 소외·가설")):
            for row in result[key]:
                rotation_count += 1
                acceleration = f"{row['accel_3m']*100:+.2f}" if row["accel_3m"] is not None else "미연결"
                flow = f"{row['money_flow_score']:.1f}" if row["money_flow_score"] is not None else "미연결"
                lines.append(" | ".join(_cell(v) for v in (market + " " + label,
                    row["ticker"] + " / " + row["benchmark"], row["date"],
                    _pct(row["rs_5d_change"]) + " / " + _pct(row["rs_20d_change"]), acceleration, flow)))
    if not rotation_count:
        lines.append("미연결 | - | - | - | - | 같은 거래일의 ETF·벤치 이력 부족")
    lines += ["", "**뉴스 촉매 후보**", "후보·기사 | 분류 | 연결 노출(수동 매핑) | 확정 여부", "--- | --- | --- | ---"]
    labels = {"ipo": "IPO·상장", "earnings": "실적", "policy": "정책", "fomc": "FOMC"}
    for row in candidates[:5]:
        lines.append(" | ".join(_cell(v) for v in (row["title"],
            ", ".join(labels.get(k, k) for k in row["candidate_tags"]), ", ".join(row["candidate_tickers"]) or "매핑 미연결",
            "후보·공식 발표일 미확인")))
    if not candidates:
        lines.append("후보 미수집 | - | - | 연결 뉴스에서 촉매 단서 미확보")
    lines += ["", "**이벤트 스터디 · 전후 5거래일**",
              f"확정 발표 시각·완료된 가격창이 연결된 표본 {study['sample_count']}건. 뉴스 후보를 역사적 이벤트로 간주하지 않습니다. 사후 분포이며 예측·인과 증명이 아닙니다."]
    if study.get("groups"):
        lines += ["종목·유형 | 표본 수 | 전 5일 중앙값 | 후 5일 중앙값 | 후 5일 25~75분위", "--- | --- | --- | --- | ---"]
        for row in study["groups"]:
            lines.append(" | ".join(_cell(v) for v in (row["ticker"] + " " + row["event_type"], row["sample_count"],
                _pct(row["pre"]["median"]), _pct(row["post"]["median"]), _pct(row["post"]["p25"]) + " ~ " + _pct(row["post"]["p75"]))))
    else:
        lines.append("역사적 확정 발표시각·거래소 일정 이력 미연결: 분포 산출 보류. 발표일만 있는 공지를 임의 시각으로 바꾸지 않습니다.")
    lines += ["", "**검증할 가설 3개**", "현재 LLM 미연결: 아래는 입력 근거만 사용하는 규칙 기반 관찰 가설입니다.",
              "가설 | 근거 | 반증 조건 | 확인 일정", "--- | --- | --- | ---"]
    for i, h in enumerate(hypotheses):
        evidence = h["evidence"]
        if i < 2:
            row = evidence[0] if evidence else {}
            claim = ("상대 주도 동행 관찰" if i == 0 else "소외 섹터의 단기 상대강도 개선 가능성") if row else "근거 부족·가설 보류"
            data = (f"{row['ticker']} {row['date']} · RS5D {_pct(row['rs_5d_change'])} / RS20D {_pct(row['rs_20d_change'])}" if row else "동일 기준일 상대강도 조건 미충족")
            falsifier = "같은 ETF RS5D 또는 RS20D가 0 이하" if i == 0 else "RS20D 회복 전 RS5D가 0 이하"
            schedule = "해당 시장 다음 확정 종가" if i == 0 else "매 확정 종가 및 5거래일 뒤"
        else:
            claim = "이벤트 전후 분포 차이 관찰" if evidence else "이벤트 반응 가설 보류"
            data = f"완료 표본 {evidence[0]['sample_count']}건" if evidence else "동종·동일 종목 완료 표본 3건 미만"
            falsifier, schedule = "추가 표본에서 중앙값 방향·분포 차이가 유지되지 않음", "다음 공식 발표 확인 후 5거래일 종료"
        lines.append(" | ".join(_cell(v) for v in (claim, data, falsifier, schedule)))
    executable = sum(text(first(row, "게이트상태", "gate_state")) in {"실행가능", "EXECUTABLE"} for row in records(summary_rows))
    lines += ["", "**실행 게이트와 관찰 슬롯**", "구분 | 상태", "--- | ---",
              f"신규 장기 편입·적립 게이트 | 기존 판정 유지 · 실행가능 {executable}개(오늘점검 입력 기준)",
              "단기 이벤트 스윙 슬롯 | 건별 손실한도 미설정 · 촉매·손절·한도는 별도 기록, 매수 허용 아님",
              "거래 기록 | 실제 체결을 ‘이벤트 장부’에 건별 수동 기록. 자동 주문·매매 연결 없음"]
    return lines
