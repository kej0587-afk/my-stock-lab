"""Render the real Today holdings panel with saved, synthetic account inputs."""

from copy import deepcopy
import socket
from unittest.mock import MagicMock

import pandas as pd
import pytest

from stock_lab_core import decision_workspace, report_latest, today_snapshot
from stock_lab_core.portfolio import apply_holdings_weight_columns, calc_portfolio_summary
from stock_lab_core.sector_display_snapshot import prepare_sector_display


@pytest.fixture
def prepared_sector_snapshot():
    def prewarm(guard, cards, flow):
        snapshot = {
            "flow_df": pd.DataFrame({"Ticker": ["MSFT"], "기준일": ["2026-11-27"]}),
            "sector_rotation_df": flow.copy(deep=True),
            "theme_rotation_df": pd.DataFrame(),
            "subtheme_group_df": pd.DataFrame(),
            "command_flow_df": flow,
        }
        unified, command = flow.copy(deep=True), flow.copy(deep=True)
        unify = MagicMock(return_value=unified)
        prepare = MagicMock(return_value=command)
        build_cards = MagicMock(return_value=cards)
        result = prepare_sector_display(
            snapshot, guard, allow_prepare=True,
            unify=unify, prepare=prepare, build_cards=build_cards,
        )
        unify.assert_called_once()
        prepare.assert_called_once()
        assert prepare.call_args.args[0] is unified
        build_cards.assert_called_once()
        assert build_cards.call_args.args[0] is command
        assert result[0] is unified and result[1] is command and result[2] is cards
        assert snapshot["_sector_display_prepared"]["cards"] is cards
        return snapshot
    return prewarm


@pytest.mark.parametrize("krw_cash,usd_cash", [(140_000., 100.), (0., 0.)])
def test_unified_briefing_preserves_parking_assets_and_saved_results(
    app_module, monkeypatch, prepared_sector_snapshot, krw_cash, usd_cash,
):
    app = app_module
    fx = 1400.
    holdings = apply_holdings_weight_columns(pd.DataFrame([
        {"티커": "MSFT", "자산명": "Example equity", "bucket": "core",
         "보유량": 20., "매입가": 110., "현재가": 100., "평가금액": 2000.,
         "원화환산": 2_800_000., "목표비중": 80.},
        {"티커": "SGOV", "자산명": "Designated parking", "bucket": "reserve",
         "보유량": 10., "매입가": 99., "현재가": 100., "평가금액": 1000.,
         "원화환산": 1_400_000., "목표비중": 10.},
    ]), krw_cash, usd_cash, fx)
    summary = pd.DataFrame([{
        "티커": "MSFT", "종목명": "Example equity", "bucket": "core",
        "현재가": 100., "게이트상태": "방어우선", "게이트근거": "시장방어: 신규매수 중단",
        "🔥기술적 타점": "100% 적립", "후보품질": "우수", "R/R": 1.36,
        "판정코드": "CORE_DCA", "가격자료기준일": "2026-11-27",
    }], index=[7])
    summary.attrs["portfolio_signal_at"] = "2026-11-28 08:30:00"
    flow = pd.DataFrame([{"Ticker": "MSFT", "Name": "Example equity", "점수": 7.1}])
    guard = {"mode": "방어", "level": "danger", "action": "신규매수 중단"}
    snapshot = prepared_sector_snapshot(guard, [], flow)
    prepared_bundle = snapshot["_sector_display_prepared"]
    risk = pd.DataFrame([{"티커": "MSFT", "사유": "시장방어"}])
    originals = [frame.copy(deep=True) for frame in (holdings, summary, flow, risk)]
    attrs_before = deepcopy(summary.attrs)
    snapshot_before = deepcopy(snapshot)
    masks = {name: pd.Series(value, index=summary.index) for name, value in (
        ("buyish_mask", False), ("wait_mask", False),
        ("caution_mask", True), ("hard_block_mask", False))}
    masks_before = {name: mask.copy(deep=True) for name, mask in masks.items()}

    ui = MagicMock()
    ui.session_state = {
        "_app_holdings_table": holdings, "_app_krw_cash": krw_cash,
        "_app_usd_cash": usd_cash, "_app_usdkrw": fx,
        "today_queue_summary_df": summary, "today_queue_summary_last_run": "2026-11-28 08:30:00",
        "acc_filter": ["synthetic"],
        app.TODAY_MARKET_FLOW_SNAPSHOT_KEY: snapshot,
    }
    ui.segmented_control.return_value = "보유관리"
    metrics = [MagicMock() for _ in range(5)]
    ui.columns.return_value = metrics
    monkeypatch.setattr(app, "st", ui)
    monkeypatch.setattr(app, "holdings_table", holdings)
    monkeypatch.setattr(app, "IS_PUBLIC_DEMO", True)
    monkeypatch.setattr(app, "CURRENT_USER_EMAIL", "")
    monkeypatch.setattr(app, "get_report_build_info", lambda _: {"loaded_source_sha256": "synthetic"})
    # Isolate report persistence and the unrelated decision selector. Keep the
    # real held metadata, flag classification, overview and asset table renderers.
    monkeypatch.setattr(report_latest, "restore_last_report", MagicMock())
    monkeypatch.setattr(report_latest, "last_report_caption", lambda _: "")
    monkeypatch.setattr(today_snapshot, "load_previous_today_summary", lambda **_: (pd.DataFrame(), ""))
    monkeypatch.setattr(decision_workspace, "render_frame_decision_brief", MagicMock())

    def unexpected_work(*args, **kwargs):
        pytest.fail("Saved-result rendering must not fetch or recompute Today")

    monkeypatch.setattr(socket.socket, "connect", unexpected_work)
    for name in ("get_all_summary", "_calculate_fresh_today_summary", "_flow_sector_ability_cards",
                 "build_today_unified_flow_candidates", "_prepare_flow_command_table"):
        monkeypatch.setattr(app, name, unexpected_work)

    cash = app.get_cash_available_for_dca(None)
    reserve = app.get_reserve_available_for_crash_buy(None)
    app.render_today_unified_briefing_panel(
        summary, market_guard=guard,
        risk_df=risk, cash_available=cash, reserve_available=reserve, **masks,
    )

    tables = [call.args[0] for call in ui.dataframe.call_args_list
              if call.args and isinstance(call.args[0], pd.DataFrame)]
    asset_tables = [frame for frame in tables if "보유분 관리" in frame.columns]
    assert len(asset_tables) == 1
    assets = asset_tables[0]
    assert assets.columns.get_loc("오늘 행동") < assets.columns.get_loc("기술적 타점")
    equity = assets.loc[assets["티커"].str.upper().eq("MSFT")].iloc[0]
    assert equity["오늘 행동"] == "실행 보류"
    assert equity["보류 사유"] == "시장방어: 신규매수 중단"
    assert equity["기술적 타점"] == "100% 적립"
    assert equity["판정·자산 대조"] == "입력 변경/미확인 · 이전 판정"
    parking = assets.loc[assets["티커"].str.upper().eq("SGOV")]
    assert len(parking) == 1
    parked = parking.iloc[0]
    assert parked["오늘 행동"] == "파킹자산 · 종목점검 제외"
    assert parked["기술적 타점"] == "해당없음"
    assert parked["보유수량"] == 10.
    assert parked["달러 평가액"] == 1000.
    assert parked["원화 환산액"] == 1_400_000.
    expected_cash = krw_cash + usd_cash * fx
    nav = 4_200_000. + expected_cash
    assert parked["현재비중"] == f"{1_400_000. / nav * 100:.1f}%"
    assert cash == expected_cash and reserve == 1_400_000.
    assert metrics[3].metric.call_args.args == ("입력 예수금(만원)", f"{expected_cash / 10000:,.1f}")
    assert metrics[4].metric.call_args.args == ("보유 파킹자산(만원)", "140.0")
    assert calc_portfolio_summary(holdings, 0., krw_cash, usd_cash, fx, None)["current_asset"] == nav
    assert metrics[1].metric.call_args.args == ("실행후보", "0개")
    assert metrics[2].metric.call_args.args == ("주의/차단", "1개")
    flags = [frame for frame in tables if "문제" in frame.columns]
    parking_flags = pd.concat(flags).loc[lambda frame: frame["티커"].eq("SGOV")]
    assert parking_flags["문제"].tolist() == ["파킹자산 · 종목점검 제외"]

    for frame, before in zip((holdings, summary, flow, risk), originals):
        pd.testing.assert_frame_equal(frame, before)
    assert summary.attrs == attrs_before
    assert snapshot["sector_cards_view_version"] == snapshot_before["sector_cards_view_version"]
    assert snapshot["sector_ability_cards"] == snapshot_before["sector_ability_cards"]
    assert snapshot["_sector_display_prepared"] is prepared_bundle
    for field in ("unified", "command"):
        pd.testing.assert_frame_equal(prepared_bundle[field], snapshot_before["_sector_display_prepared"][field])
    for field in ("sector_rotation_df", "theme_rotation_df", "subtheme_group_df"):
        pd.testing.assert_frame_equal(snapshot[field], snapshot_before[field])
    for name, mask in masks.items():
        pd.testing.assert_series_equal(mask, masks_before[name])
    assert ui.session_state["today_queue_summary_df"] is summary
    assert ui.session_state["_app_holdings_table"] is holdings
    assert ui.session_state[app.TODAY_MARKET_FLOW_SNAPSHOT_KEY] is snapshot


def test_matching_context_passes_current_evidence_and_exchange_dates_to_history(
    app_module, monkeypatch, prepared_sector_snapshot,
):
    from stock_lab_core import report_eventstudy, report_history_store, today_change_brief
    from stock_lab_core.report_history import normalized_decisions

    app = app_module
    owner = "synthetic@example.invalid"
    accounts = ["synthetic-ISA", "synthetic-US"]
    summary = pd.DataFrame([
        {"티커": ticker, "종목명": ticker, "bucket": "core", "현재가": 100.,
         "게이트상태": "방어우선", "게이트근거": "시장방어",
         "🔥기술적 타점": "100% 적립", "돈흐름_판정": flow,
         "가격자료기준일": "2026-11-27"}
        for ticker, flow in (("MSFT", "회복"), ("005930.KS", "관찰"))
    ])
    holdings = pd.DataFrame([{"티커": "MSFT", "bucket": "core", "보유량": 2.,
                              "매입가": 100., "현재비중": 20., "목표비중": 30.}])
    cards = [{"market": "미국", "rank": 1, "title": "금융", "total": 7.1}]
    guard = {"mode": "방어", "level": "danger"}
    snapshot = prepared_sector_snapshot(
        guard, cards, pd.DataFrame([{"Ticker": "MSFT", "Name": "MSFT", "점수": 7.1}]))
    prepared_bundle = snapshot["_sector_display_prepared"]
    snapshot_before = deepcopy(snapshot)
    ui = MagicMock()
    ui.session_state = {
        "acc_filter": accounts, "_app_holdings_table": holdings,
        "today_queue_summary_df": summary,
        app.TODAY_MARKET_FLOW_SNAPSHOT_KEY: snapshot,
    }
    ui.segmented_control.return_value = "보유관리"
    ui.columns.return_value = [MagicMock() for _ in range(5)]
    monkeypatch.setattr(app, "st", ui)
    monkeypatch.setattr(app, "holdings_table", holdings)
    monkeypatch.setattr(app, "IS_PUBLIC_DEMO", False)
    monkeypatch.setattr(app, "CURRENT_USER_EMAIL", owner)
    client = object()
    monkeypatch.setattr(app, "supabase", client)
    monkeypatch.setattr(app, "get_report_build_info", lambda _: {"loaded_source_sha256": "synthetic"})
    summary.attrs.update(portfolio_signal_context=app.portfolio_signal_input_context(),
                         portfolio_signal_at="2026-11-28T08:30:00+09:00")
    before, held_before = summary.copy(deep=True), holdings.copy(deep=True)
    attrs_before = deepcopy(summary.attrs)
    store = MagicMock()
    store_factory = MagicMock(return_value=store)
    monkeypatch.setattr(report_history_store, "SupabaseReportHistoryStore", store_factory)
    monkeypatch.setattr(report_latest, "SupabaseReportLatestStore", MagicMock())
    monkeypatch.setattr(report_latest, "restore_last_report", MagicMock())
    monkeypatch.setattr(report_latest, "last_report_caption", lambda _: "")
    monkeypatch.setattr(today_snapshot, "load_previous_today_summary", lambda **_: (pd.DataFrame(), ""))
    monkeypatch.setattr(decision_workspace, "render_frame_decision_brief", MagicMock())
    expected_previous = {"KR": "2026-11-26", "US": "2026-11-25"}
    response = {"headline": "합성 비교 결과 · 신규 주문 보류",
                "audit": {"coverage_note": "합성 비교 근거", "excluded": []},
                "comparison_dates": expected_previous,
                "comparison_generated_at": "2026-11-27T08:30:00+09:00",
                "persistence": {"status": "mocked"}}
    refresh = MagicMock(return_value=response)
    monkeypatch.setattr(today_change_brief, "refresh_today_change_brief", refresh)
    # Exercise the bundled calendar implementation, including Thanksgiving;
    # this spy records calls but does not replace calendar results.
    calendar = MagicMock(wraps=report_eventstudy._exchange_schedule)
    monkeypatch.setattr(report_eventstudy, "_exchange_schedule", calendar)

    def unexpected_work(*args, **kwargs):
        pytest.fail("Saved evidence integration must not fetch or recompute Today")

    monkeypatch.setattr(socket.socket, "connect", unexpected_work)
    for name in ("get_all_summary", "_calculate_fresh_today_summary", "_flow_sector_ability_cards",
                 "build_today_unified_flow_candidates", "_prepare_flow_command_table"):
        monkeypatch.setattr(app, name, unexpected_work)
    false_mask = pd.Series(False, index=summary.index)
    app.render_today_unified_briefing_panel(
        summary, market_guard=guard,
        buyish_mask=false_mask, wait_mask=false_mask, hard_block_mask=false_mask,
        caution_mask=~false_mask,
    )

    refresh.assert_called_once()
    call = refresh.call_args
    assert call.args[0] is ui.session_state
    observation = call.args[1]
    assert observation["dates"] == {"KR": "2026-11-27", "US": "2026-11-27"}
    assert observation["generated_at"] == "2026-11-28T08:30:00+09:00"
    assert observation["account_key"] == report_latest.account_key(accounts)
    assert observation["rows"] == normalized_decisions(summary.to_dict("records"))
    assert observation["comparison_context"] == {
        "schema": "today-overview-v2", "sector_source": "same-session-ranked-cards",
        "recovery_source": "saved-flow-recovery-label"}
    assert observation["brief_inputs"] == {
        "sector_leaders": {"미국": "금융"}, "recovery_watch": ["MSFT"],
        "execution_count": 0, "held_actions": {"msft": "실행 보류 · 시장방어"}}
    assert call.kwargs["owner_scope"] == owner
    assert call.kwargs["accounts"] == accounts
    assert call.kwargs["store"] is store
    assert call.kwargs["previous_sessions"] == expected_previous
    assert call.kwargs["today_action"] == "신규 주문 보류, 보유 위험과 자료 오류 확인"
    assert call.kwargs["static_policy"]
    store_factory.assert_called_once_with(client, owner_scope=owner)
    assert store.mock_calls == []  # No actual persistence: refresh is mocked.
    assert [item.args for item in calendar.call_args_list] == [
        ("KR", "2026-11-11", "2026-11-26"), ("US", "2026-11-11", "2026-11-26")]
    displayed = "\n".join(str(item.args[0]) for item in ui.markdown.call_args_list if item.args)
    assert response["headline"] in displayed
    tables = [item.args[0] for item in ui.dataframe.call_args_list
              if item.args and isinstance(item.args[0], pd.DataFrame)]
    assets = next(frame for frame in tables if "판정·자산 대조" in frame.columns)
    assert assets.iloc[0]["판정·자산 대조"] == "계산 입력 일치"
    assert assets.iloc[0]["오늘 행동"] == "실행 보류"
    assert assets.iloc[0]["기술적 타점"] == "100% 적립"
    sectors = next(frame for frame in tables if "섹터 관찰" in frame.columns)
    assert sectors.iloc[0]["시장"] == "미국"
    assert sectors.iloc[0]["섹터"] == "금융"
    assert sectors.iloc[0]["기존 점수"] == 7.1
    assert snapshot["sector_ability_cards"] is cards
    assert snapshot["_sector_display_prepared"] is prepared_bundle
    for field in ("unified", "command"):
        pd.testing.assert_frame_equal(prepared_bundle[field], snapshot_before["_sector_display_prepared"][field])
    for field in ("sector_rotation_df", "theme_rotation_df", "subtheme_group_df", "command_flow_df"):
        pd.testing.assert_frame_equal(snapshot[field], snapshot_before[field])
    pd.testing.assert_frame_equal(summary, before)
    pd.testing.assert_frame_equal(holdings, held_before)
    assert summary.attrs == attrs_before
    assert ui.session_state["_app_holdings_table"] is holdings


@pytest.mark.parametrize("context_case", ["mismatch", "missing", "stale_reason"])
def test_stale_context_never_refreshes_history_with_owner_dates_and_timestamp(
    app_module, monkeypatch, context_case,
):
    from stock_lab_core import today_change_brief
    from stock_lab_core.today_overview import observed_sessions

    app = app_module
    summary = pd.DataFrame([
        {"티커": ticker, "종목명": ticker, "게이트상태": "방어우선",
         "게이트근거": "시장방어", "🔥기술적 타점": "100% 적립",
         "가격자료기준일": "2026-11-27"}
        for ticker in ("MSFT", "005930.KS")
    ])
    summary.attrs["portfolio_signal_at"] = "2026-11-28T08:30:00+09:00"
    ui = MagicMock()
    ui.session_state = {"acc_filter": ["synthetic"], "today_queue_summary_df": summary}
    ui.segmented_control.return_value = "보유관리"
    ui.columns.return_value = [MagicMock() for _ in range(5)]
    monkeypatch.setattr(app, "st", ui)
    monkeypatch.setattr(app, "holdings_table", pd.DataFrame())
    monkeypatch.setattr(app, "IS_PUBLIC_DEMO", False)
    monkeypatch.setattr(app, "CURRENT_USER_EMAIL", "synthetic@example.invalid")
    monkeypatch.setattr(app, "supabase", None)
    monkeypatch.setattr(app, "get_report_build_info", lambda _: {"loaded_source_sha256": "synthetic"})
    actual_context = app.portfolio_signal_input_context()
    assert actual_context
    if context_case == "mismatch":
        summary.attrs["portfolio_signal_context"] = "obsolete-input-context"
        assert summary.attrs["portfolio_signal_context"] != actual_context
    elif context_case == "stale_reason":
        summary.attrs["portfolio_signal_context"] = actual_context
        summary.attrs["today_queue_summary_stale_reason"] = "계좌 입력 변경"
    before = summary.copy(deep=True)
    before_attrs = deepcopy(summary.attrs)
    # Ensure context is the only missing eligibility condition, not absent
    # ownership, one-market coverage, a missing time or a naive timestamp.
    assert observed_sessions(summary) == {"KR": "2026-11-27", "US": "2026-11-27"}
    assert pd.Timestamp(summary.attrs["portfolio_signal_at"]).tzinfo is not None
    refresh = MagicMock(side_effect=AssertionError("Stale context must not save/compare history"))
    monkeypatch.setattr(today_change_brief, "refresh_today_change_brief", refresh)
    make_session = MagicMock(side_effect=AssertionError("Stale context must not build history"))
    monkeypatch.setattr(today_change_brief, "make_today_change_session", make_session)
    monkeypatch.setattr(report_latest, "restore_last_report", MagicMock())
    monkeypatch.setattr(report_latest, "last_report_caption", lambda _: "")
    monkeypatch.setattr(today_snapshot, "load_previous_today_summary", lambda **_: (pd.DataFrame(), ""))
    monkeypatch.setattr(decision_workspace, "render_frame_decision_brief", MagicMock())

    def unexpected_work(*args, **kwargs):
        pytest.fail("Stale display must not fetch or recompute Today")

    monkeypatch.setattr(socket.socket, "connect", unexpected_work)
    for name in ("get_all_summary", "_calculate_fresh_today_summary", "_flow_sector_ability_cards",
                 "build_today_unified_flow_candidates", "_prepare_flow_command_table"):
        monkeypatch.setattr(app, name, unexpected_work)
    false_mask = pd.Series(False, index=summary.index)
    app.render_today_unified_briefing_panel(
        summary, market_guard={"mode": "방어", "level": "danger"},
        buyish_mask=false_mask, wait_mask=false_mask, hard_block_mask=false_mask,
        caution_mask=~false_mask,
    )
    refresh.assert_not_called()
    make_session.assert_not_called()
    displayed = "\n".join(str(call.args[0]) for call in ui.markdown.call_args_list if call.args)
    assert "현재 계좌·입력 기준 재계산 필요" in displayed
    assert "이력 비교·저장 보류" in displayed
    pd.testing.assert_frame_equal(summary, before)
    assert summary.attrs == before_attrs
    assert ui.session_state["today_queue_summary_df"] is summary
