"""Today Queue details only; inputs are already classified by the application."""

from datetime import datetime, timedelta, timezone

import pandas as pd

from stock_lab_core.backup import dataframe_to_csv_bytes
from stock_lab_core.execution_readiness import execution_guidance_fields
from stock_lab_core.formatters import normalize_ticker
from stock_lab_core.report_build import register_loaded_source
from stock_lab_core.today_queue import sort_today_queue_detail_table

register_loaded_source(__name__, __file__)


DETAIL_COLUMNS = [
    "종목명", "티커", "유형", "현재가", "기업품질", "🔥기술적 타점", "게이트상태", "게이트근거", "후보품질", "후보점수", "후보검토사항",
    "가격자료기준일", "가격신선도근거", "돈흐름기준일", "돈흐름신선도근거", "재무자료기간", "재무자료상태", "가격반영", "지표마지막봉", "계산시각", "자료주의",
    "돈흐름_연결경로", "돈흐름_연결사유", "돈흐름_연결보완사유",
    "목표가요약", "최종읽기", "현재실행안내", "R/R", "R/R성격", "R/R출처", "차트목표", "손절가",
    "1차기준", "현재진입조건", "부족액", "📌후보등급",
    "패턴타점", "패턴근거", "돈흐름_후보군", "돈흐름_판정", "돈흐름_주의요인", "돈흐름_시장맥락",
    "핵심근거", "안전상태", "매크로상태", "데이터상태", "Adj점수", "RS", "섹터RS", "섹터RS상태", "섹터벤치", "섹터RS변화", "섹터RS기준일", "섹터분류근거", "섹터분류출처", "섹터검증일", "RSI", "MFI", "볼린저 %B", "고점대비",
]


def prepare_detail_view(summary_df):
    """Build presentation fields once per render without changing stored decisions."""
    view_df = summary_df.copy()
    if view_df.empty:
        return view_df
    guidance = pd.DataFrame([execution_guidance_fields(row) for row in view_df.to_dict("records")], index=view_df.index)
    for col in guidance:
        view_df[col] = guidance[col]
    return view_df


def _render_concentration(st, summary_df, watch_items, execution_mask, candidate_focus_mask):
    if candidate_focus_mask.sum() >= 2 and "티커" in summary_df.columns:
        _ticker_to_class = {
            str(it.get("ticker", "")).strip().upper(): str(it.get("asset_class", "")).strip()
            for it in watch_items
        }
        _class_buckets: dict[str, list[str]] = {}
        for _tkr in summary_df.loc[candidate_focus_mask, "티커"].astype(str).str.upper():
            _cls = _ticker_to_class.get(_tkr, "")
            if _cls:
                _class_buckets.setdefault(_cls, []).append(_tkr)
        _concentrated = {cls: tks for cls, tks in _class_buckets.items() if len(tks) >= 2}
        if _concentrated:
            _warn_parts = [f"**{cls}** ({', '.join(tks)})" for cls, tks in _concentrated.items()]
            _concentration_text = " / ".join(_warn_parts)
            if int(execution_mask.sum()) >= 1:
                st.warning(
                    "⚠️ **섹터 집중 주의** — 같은 섹터에 실행/관심 후보가 2개 이상입니다: "
                    + _concentration_text
                    + "\n\n동시에 진입하면 해당 섹터 비중이 집중될 수 있습니다. 분할 우선순위를 정한 뒤 순차 접근을 권장합니다."
                )
            else:
                st.caption(
                    "섹터 집중 참고: 현재 실행 후보는 0개라 경고가 아니라 관찰용입니다. "
                    + _concentration_text
                )


def _render_detail_table(st, view_df: pd.DataFrame, empty_msg: str, sort_low_first: bool = False):
    if view_df is None or view_df.empty:
        st.info(empty_msg)
        return
    view_df = view_df.copy()
    view_df = sort_today_queue_detail_table(view_df, risk_first=sort_low_first)
    display_cols = [col for col in DETAIL_COLUMNS if col in view_df.columns]
    for state_col in ["매크로상태", "데이터상태"]:
        if state_col in display_cols and view_df[state_col].astype(str).nunique(dropna=False) <= 1:
            state_value = str(view_df[state_col].astype(str).iloc[0])
            st.caption(f"{state_col}: {state_value} (현재 표 전 종목 동일)")
            display_cols.remove(state_col)
    if "애널목표Upside" in display_cols:
        missing_analyst_targets = view_df["애널목표Upside"].astype(str).str.strip().isin(["", "-", "—", "nan", "None"]).sum()
        if missing_analyst_targets:
            st.caption(
                f"애널목표Upside 없음 {int(missing_analyst_targets)}개: 국내 중소형/우선주/ETF는 목표가 소스가 비어 있을 수 있어 차트목표와 R/R을 우선 참고합니다."
            )
    st.dataframe(
        view_df[display_cols],
        column_config={
            "애널목표Upside": st.column_config.TextColumn("애널목표Upside", help="애널리스트 평균 목표가 기준 현재가 대비 상승여력입니다. R/R용 차트목표와 다른 값입니다. 데이터 없으면 — 표시"),
            "목표가요약": st.column_config.TextColumn("목표가요약", help="애널 목표가, 상승여력, 참여수만 압축 표시합니다. 출처 URL/조회시각은 기본표에서 숨깁니다."),
            "애널목표출처": st.column_config.TextColumn("애널목표출처", help="목표가를 제공한 데이터 소스입니다."),
            "애널목표출처URL": st.column_config.LinkColumn("애널목표출처URL", display_text="원자료"),
            "애널목표기준일": st.column_config.TextColumn("애널목표기준일", help="제공처가 명시한 목표가 기준일입니다. 기준일을 제공하지 않으면 비워 둡니다."),
            "후보품질": st.column_config.TextColumn("기존 종합후보", help="기술·재무 혼합 순위입니다. 별도의 기업 품질 점수와 실행 게이트에 다시 합산하지 않습니다."),
            "섹터분류출처": st.column_config.LinkColumn("섹터분류출처", display_text="분류 근거"),
            "섹터RS변화": st.column_config.NumberColumn("섹터RS변화", format="%.2f%%", help="동일 거래일의 종목/벤치 가격비가 관측기간 동안 변한 비율입니다."),
            "업사이드상태": st.column_config.TextColumn("업사이드상태", help="애널 목표가 업사이드 데이터의 사용 가능 상태입니다."),
            "게이트상태": st.column_config.TextColumn("1차 게이트", help="종목 선별 결과입니다. 정밀관측소 최종 체크의 실행 허용과 구분합니다."),
            "게이트근거": st.column_config.TextColumn("게이트근거", help="실행 후보에서 대기/방어로 내려간 직접 사유입니다."),
            "현재실행안내": st.column_config.TextColumn("현재 실행 안내"),
            "R/R": st.column_config.TextColumn("R/R", help="정밀관측소와 같은 2ATR 손절 기준의 현재가 손익비입니다. 일반 표에서는 Adj점수 다음 정렬 기준입니다."),
            "R/R성격": st.column_config.TextColumn("R/R성격", help="차트 구조 고점 기준인지, 현재가+4ATR 투영 상단인지 구분합니다."),
            "R/R출처": st.column_config.TextColumn("R/R출처", help="R/R 목표값을 산출한 기준입니다. 투영상단은 확정 목표가가 아닙니다."),
            "섹터RS상태": st.column_config.TextColumn("섹터RS상태", help="섹터 RS가 강함/보통/약함인지, 또는 섹터 벤치 미매핑인지 보여줍니다."),
            "돈흐름_판정": st.column_config.TextColumn("돈흐름_판정", help="돈흐름 후보판에서 같은 종목을 어떻게 보고 있는지입니다."),
            "돈흐름_주의요인": st.column_config.TextColumn("돈흐름_주의요인", help="돈흐름 후보판의 과열, 내부확산, 약한축 등 주의 사유입니다."),
            "차트목표": st.column_config.TextColumn("차트목표", help="R/R 계산에 쓰는 차트 구조 목표가 또는 강세 시나리오 상단입니다. 애널리스트 목표가와 다를 수 있습니다."),
            "손절가": st.column_config.TextColumn("손절가", help="R/R 계산에 쓰는 2ATR 기준 손절선입니다."),
            "1차기준": st.column_config.TextColumn("1차기준", help="현재가 실행이 아니면 MA5/MA20/FVG/ATR 중 가장 가까운 1차 확인 가격입니다."),
            "현재진입조건": st.column_config.TextColumn("현재 진입 조건"),
            "부족액": st.column_config.TextColumn("부족액", help="목표비중 대비 남은 매수 필요액입니다. 실제 주문 전에는 정밀관측소에서 회차 금액을 다시 확인하세요."),
        },
        width='stretch',
        hide_index=True,
    )
    with st.expander("기술 원계획 · 실행 허용 아님"):
        raw_cols = [col for col in ("종목명", "티커", "실행메모", "1차조건") if col in view_df]
        st.dataframe(view_df[raw_cols], width='stretch', hide_index=True)
    st.download_button(
        "현재 표 CSV 다운로드 (앱 정렬 고정)",
        data=dataframe_to_csv_bytes(view_df[display_cols]),
        file_name=f"today_queue_detail_{datetime.now(timezone(timedelta(hours=9))).strftime('%Y%m%d_%H%M')}.csv",
        mime="text/csv",
        key=f"download_today_queue_detail_{abs(hash(empty_msg))}_{sort_low_first}_{len(view_df)}",
        width='stretch',
    )


def _render_queue_tabs(st, summary_df, queue_masks, flow_shortlist_df,
                       get_cached_today_market_flow_snapshot, render_today_flow_shortlist_panel):
    detail_df = prepare_detail_view(summary_df)
    tabs = st.tabs([
        f"실행 후보 ({int(queue_masks['execution'].sum())})",
        f"관심/눌림대기 ({int(queue_masks['wait'].sum())})",
        f"돈흐름 후보 ({len(flow_shortlist_df)})",
        f"비중초과 방어 ({int(queue_masks['overweight'].sum())})",
        f"시장방어 ({int(queue_masks['market_defense'].sum())})",
        f"가격방어 ({int(queue_masks['price_defense'].sum())})",
        f"급락방어 ({int(queue_masks['rapid_drop'].sum())})",
        f"추세방어 ({int(queue_masks['structure'].sum())})",
        f"과열/타점대기 ({int(queue_masks['overheat'].sum())})",
        f"데이터확인 ({int(queue_masks['data_issue'].sum())})",
        f"기타/관망 ({int(queue_masks['other_caution'].sum())})",
        "전체",
    ])
    with tabs[0]:
        st.caption("정밀관측소에서 비중·현금·당일 변동성만 확인하면 실행 후보로 볼 수 있는 그룹입니다.")
        _render_detail_table(st, detail_df.loc[queue_masks["execution"]], "현재 바로 실행 후보로 볼 종목은 없습니다.")
    with tabs[1]:
        st.caption("최종읽기 기준: `👀돌파대기`는 관심등록, `✅정밀확인`은 정밀관측소 확인, `⏳눌림대기`와 `⏳DCA조건부`는 추격보다 조건 확인/다음 눌림 대기입니다.")
        _render_detail_table(st, detail_df.loc[queue_masks["wait"]], "관심/눌림대기 종목이 없습니다.")
    with tabs[2]:
        render_today_flow_shortlist_panel(
            get_cached_today_market_flow_snapshot(),
            shortlist_df=flow_shortlist_df,
            key_prefix="today_queue_flow_shortlist",
            show_header=False,
        )
    with tabs[3]:
        st.caption("비중초과/목표비중 충족은 시장이 나빠서가 아니라 추가매수 금지와 리밸런싱 점검 신호입니다.")
        _render_detail_table(st, detail_df.loc[queue_masks["overweight"]], "비중초과 방어 대상이 없습니다.", sort_low_first=True)
    with tabs[4]:
        st.caption("시장 전체 위험 때문에 신규/추매를 멈추는 그룹입니다. 기존 보유 전량 매도 신호가 아니라 비중·손절선·하락 원인 점검 신호입니다.")
        _render_detail_table(st, detail_df.loc[queue_masks["market_defense"]], "시장방어로 분류된 종목이 없습니다.", sort_low_first=True)
    with tabs[5]:
        st.caption("고점대비 낙폭이 커진 종목입니다. 추세훼손 확정이 아니라 새 돈 투입 전 하락 원인과 종가 안정부터 보는 그룹입니다.")
        _render_detail_table(st, detail_df.loc[queue_masks["price_defense"]], "가격방어로 분류된 종목이 없습니다.", sort_low_first=True)
    with tabs[6]:
        st.caption("RS가 살아 있어도 하루 급락봉과 거래량이 잡힌 종목입니다. 신규/추매보다 종가와 다음 봉 회복을 먼저 봅니다.")
        _render_detail_table(st, detail_df.loc[queue_masks["rapid_drop"]], "급락방어로 분류된 종목이 없습니다.", sort_low_first=True)
    with tabs[7]:
        st.caption("MA50 이탈, MA20 하회+RS 약함 등 실제 추세 조건이 약해진 종목입니다. 신규매수보다 손절선·보유근거·회복조건을 먼저 봅니다.")
        _render_detail_table(st, detail_df.loc[queue_masks["structure"]], "추세방어로 분류된 종목이 없습니다.", sort_low_first=True)
    with tabs[8]:
        st.caption("볼린저 상단, 과열, 추격금지, MFI 과열 등 가격 위치 때문에 대기하는 그룹입니다.")
        _render_detail_table(st, detail_df.loc[queue_masks["overheat"]], "과열/타점대기 종목이 없습니다.", sort_low_first=True)
    with tabs[9]:
        st.caption("가격 이력 또는 지표 계산을 못 불러온 항목입니다. 현재가는 보조 조회로 표시될 수 있지만, 일봉 이력이 없으면 판정은 보류합니다.")
        _render_detail_table(st, detail_df.loc[queue_masks["data_issue"]], "데이터확인 항목이 없습니다.", sort_low_first=True)
    with tabs[10]:
        st.caption("위 방어/대기/데이터확인 그룹에 들어가지 않은 기타 관망 항목입니다.")
        _render_detail_table(st, detail_df.loc[queue_masks["other_caution"]], "기타/관망 항목이 없습니다.", sort_low_first=True)
    with tabs[11]:
        _render_detail_table(st, detail_df, "전체 점검 종목이 없습니다.")


def render_today_queue_details(st, summary_df, *, queue_masks, flow_shortlist_df,
        market_guard, watch_items, holdings_df, render_today_review_export_download,
        render_today_research_links_panel, get_cached_today_market_flow_snapshot,
        render_today_flow_shortlist_panel, render_summary_signal_validation_panel,
        render_today_candidate_tools):
    _render_concentration(st, summary_df, watch_items, queue_masks["execution"],
                          queue_masks["execution"] | queue_masks["wait"])
    st.divider()
    st.markdown("#### 세부 근거: 상세 판정표")

    unique_detail_count = (
        int(summary_df["티커"].astype(str).map(normalize_ticker).nunique())
        if "티커" in summary_df.columns else int(len(summary_df))
    )
    st.caption(
        f"탭 숫자는 대표 사유 기준으로 배타 분류합니다. "
        f"고유 상세판정 {unique_detail_count}개, 돈흐름 후보 {len(flow_shortlist_df)}개는 별도 참고 목록입니다."
    )
    render_today_review_export_download(
        summary_df,
        flow_shortlist_df=flow_shortlist_df,
        holdings_df=holdings_df,
        masks={
            "execution": queue_masks["execution"],
            "wait": queue_masks["wait"],
            "overweight": queue_masks["overweight"],
            "market_defense": queue_masks["market_defense"],
            "price_defense": queue_masks["price_defense"],
            "rapid_drop": queue_masks["rapid_drop"],
            "structure": queue_masks["structure"],
            "overheat": queue_masks["overheat"],
            "data_issue": queue_masks["data_issue"],
            "other_caution": queue_masks["other_caution"],
        },
        market_guard=market_guard,
    )
    with st.expander("외부 리서치 빠른 링크", expanded=False):
        render_today_research_links_panel(summary_df)

    _render_queue_tabs(st, summary_df, queue_masks, flow_shortlist_df,
        get_cached_today_market_flow_snapshot, render_today_flow_shortlist_panel)

    render_summary_signal_validation_panel(
        summary_df,
        key_prefix="today_queue_signal_validation",
        title="🧪 오늘점검 신호 과거 검증",
    )

    st.caption(
        "후보표는 매수 지시가 아니라 정밀관측소로 보낼 우선순위입니다. "
        "일반 표 정렬은 Adj점수 → R/R → 최종읽기 순서이고, 방어 탭은 위험 큰 순으로 따로 봅니다. "
        "고정된 우선순위 CSV는 표 아래 다운로드 버튼을 사용하세요. "
        "애널목표Upside는 애널리스트 목표가, 차트목표는 R/R 계산용 가격이라 서로 다를 수 있습니다."
    )

    st.divider()
    render_today_candidate_tools(summary_df, start_index=0, market_guard=market_guard)
