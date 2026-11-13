"""Report-only input labels; never infer account state from an empty queue."""

from stock_lab_core.report_build import register_loaded_source

register_loaded_source(__name__, __file__)

MISSING_ACCOUNT = "입력 미수집 — 이 리포트의 계좌 판단 불가"


def report_scope_lines(rows):
    if not rows:
        return ["**시장 전용 리포트 · 계좌 입력 미연결**", "",
                "> 오늘점검 계산 결과가 연결되지 않았습니다. 보유·관심 건수, 계좌 영향, 종목 판정·이력은 확인할 수 없습니다. 계좌 연결 리포트는 오늘점검 계산 후 다시 생성해 주세요."]
    return ["**계좌 연결 리포트 · 오늘점검 입력 기준**", "",
            "계산된 종목 목록을 연결했습니다. 시세 연결률·입력 기준일은 별도이며 전체 계좌 연결이나 최신성을 보증하지 않습니다."]


def report_count_status(rows, held_count, executable):
    if not rows:
        return "매수 허용 여부 미확인 / 보유 미수집, 관심 미수집"
    return f"신규매수 허용 {executable}개 / 보유 {held_count}, 관심 {len(rows) - held_count}"


def history_panel_lines(rows, context):
    from stock_lab_core.report_comparison import history_comparison_lines
    from stock_lab_core.report_presentation import kst_time

    lines = ["", "## 판정 이력 비교"]
    if not rows:
        return lines + ["점검 판정 입력 미연결: 이력 비교·저장을 수행하지 않았습니다. 과거 이력의 존재 여부나 소실을 뜻하지 않습니다."]
    baselines = [{"previous": context.get("previous_summary"), "previous_date": context.get("previous_date", ""),
                  "current_date": context.get("summary_date", "")}]
    if context.get("previous_run_summary"):
        baselines.append({"previous": context["previous_run_summary"], "previous_date": context.get("previous_run_date", ""),
                          "current_date": context.get("summary_date", ""), "same_session": True,
                          "previous_run_at": context.get("previous_run_at", "")})
    backend = context.get("history_backend", "none")
    # A missing input or failed read does not prove history was lost.
    if context.get("previous_summary") or context.get("previous_run_summary") or (
            context.get("history_read_status") == "loaded" and not context.get("history_error")):
        lines.extend(history_comparison_lines(rows, baselines))
        if not context.get("previous_run_summary") and not context.get("previous_summary"):
            lines.append("조회된 저장소에 비교 가능한 이전 판정 이력이 없습니다. 매크로 변화와 종목 판정 비교는 별도 저장 자료를 사용합니다.")
    else:
        lines.append("판정 이력 조회 미확인: 이전 이력이 없거나 삭제됐다고 판단하지 않습니다.")
    if context.get("previous_generated_at"):
        lines.append("이전 저장 생성 시각: " + kst_time(context["previous_generated_at"]))
    if context.get("previous_summary") and not context.get("previous_source_provenance"):
        lines.append("이전 저장본에는 지수별 출처·수집 시각이 없어 날짜 지연 원인을 확정할 수 없습니다. 현재 기준일은 UTC 날짜 계산이 아니라 각 지수의 확인된 종가 날짜이며, 새 이력부터 원자료 기준일·출처를 함께 저장합니다.")
    if context.get("history_status"):
        lines += ["", context["history_status"]]
    if backend == "local" and not context.get("history_durable"):
        lines.append("로컬 저장본 사용 중: 재배포 시 유지되지 않을 수 있습니다. 외부 저장 상태를 확인하세요.")
    return lines
