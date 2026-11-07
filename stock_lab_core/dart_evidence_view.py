"""Explicit precision evidence UI; never updates saved financial grades."""

from datetime import datetime, timedelta, timezone
from hashlib import sha256
from pathlib import Path

from stock_lab_core.dart_evidence import MAX_BYTES, canonical_bytes, stamp, validate_bundle
from stock_lab_core.dart_evidence_preview import LABELS, coverage_rows, metric_rows, preview_file, verified_codes
from stock_lab_core.financial_freshness import financial_basis

SQL_PATH = Path(__file__).resolve().parents[1] / "docs" / "20261107_dart_evidence.sql"


def panel_key(owner, ticker):
    return "dart_evidence_" + sha256(f"{str(owner).strip().lower()}|{ticker}".encode()).hexdigest()[:20]


def _error(st, error):
    code = str(error)
    if code == "schema_unavailable":
        st.warning("개인 근거 저장 테이블이 아직 없습니다. 관리자 설정 후 가져오기를 다시 눌러 주세요.")
        st.caption("설정문은 공유 Supabase 프로젝트에 전용 테이블 하나를 추가합니다. 기존 점수·계좌 테이블은 변경하지 않습니다. 앱은 설정문을 자동 실행하지 않습니다.")
        st.download_button("테이블 설정문 받기", SQL_PATH.read_text(encoding="utf-8"),
                           file_name=SQL_PATH.name, mime="text/plain", key="dart_evidence_schema_download")
    elif code in {"selected_ticker_mismatch", "ticker_mismatch", "corporate_id_mismatch"}:
        st.error("선택 종목과 파일의 기업 정보가 다릅니다. 해당 종목의 파일을 선택해 주세요.")
    elif code in {"identity_map_required", "identity_expired", "listing_unavailable_or_mismatch"}:
        st.warning("기업코드·상장시장을 확인하지 못했습니다. 미리보기만 가능하며 저장은 보류합니다.")
    elif code in {"store_unavailable", "write_unconfirmed"}:
        st.warning("저장소 응답을 확인하지 못했습니다. 저장 완료로 처리하지 않았습니다. 같은 파일로 다시 확인할 수 있습니다.")
    else:
        st.warning("자료 형식·시점 또는 연결 상태를 확인하지 못했습니다. 기존 점수와 저장 자료는 유지됩니다.")


def _show(st, payload, summary, fin_meta, extract_metrics, now):
    collected = stamp(payload["collected_at"])
    st.dataframe([{"종목": payload["ticker"], "기업코드": payload["corp_code"],
                   "수집 시각(KST)": collected.astimezone(timezone(timedelta(hours=9))).strftime("%Y-%m-%d %H:%M"),
                   "자료 나이": f"{max(0, (now-collected).total_seconds()) / 3600:.1f}시간",
                   "자료 상태": {"recent": "최근 수집", "stale": "낡은 자료", "expired": "만료 · 열람만 가능"}[summary["freshness"]],
                   "저장 점수 기준": financial_basis(fin_meta)["재무자료기간"]}], hide_index=True, width="stretch")
    st.dataframe(coverage_rows(payload), hide_index=True, width="stretch")
    if payload["reports"]:
        try:
            st.dataframe(metric_rows(payload, extract_metrics), hide_index=True, width="stretch",
                         column_config={"공시 원문": st.column_config.LinkColumn("공시 원문", display_text="DART 원문")})
        except Exception:
            st.warning("금액 요약을 만들지 못했습니다. 원자료 조회 상태만 표시하며 기존 점수는 유지합니다.")
    st.caption("로컬 수집·업로드 / 원문 서명 미검증. 최근 수집은 최신 실적 발표 전체 반영을 뜻하지 않습니다. 금액은 원통화 기준이며 저장 점수에 자동 반영되지 않습니다.")


def render_dart_evidence(st, *, ticker, owner, fin_meta, extract_metrics, identity_loader,
                         store_factory, is_demo=False, now=None, uploader=None):
    """Network/storage operations happen only on their labelled buttons."""
    current = now or datetime.now(timezone.utc)
    prefix = panel_key(owner, ticker)
    st.markdown("#### 로컬 DART 자료 가져오기 · 점수 유지")
    st.caption("집 PC에서 수집한 JSON을 검토 근거로 보관합니다. 업로드만으로는 저장되지 않습니다.")
    uploaded = (uploader or st.file_uploader)("DART 근거 파일 (JSON · 최대 8 MiB)", type=["json"],
                                              key=prefix + "_file", max_upload_size=8)
    payload = summary = None
    if uploaded is not None:
        try:
            uploaded.seek(0)
            payload, summary = preview_file(uploaded.read(MAX_BYTES + 1), ticker, now=current)
            _show(st, payload, summary, fin_meta, extract_metrics, current)
        except Exception as error:
            _error(st, error)
    if is_demo or not owner:
        st.info("공개 데모에서는 미리보기만 지원합니다. 개인 계정에서 기업 확인·저장을 사용할 수 있습니다.")
        return
    if st.button("기업·상장시장 확인", key=prefix + "_verify"):
        st.session_state.pop(prefix + "_identity", None)
        try:
            with st.spinner("기업코드·상장시장 확인 중..."):
                st.session_state[prefix + "_identity"] = identity_loader(ticker)
        except Exception as error:
            _error(st, error)
        current = now or datetime.now(timezone.utc)
    codes = verified_codes(st.session_state.get(prefix + "_identity"), ticker, current)
    eligible = False
    if codes:
        st.caption("선택 종목의 기업코드·상장시장 확인됨 (최대 10분 유효). 업로드 원문 자체의 인증은 아닙니다.")
        if payload:
            try:
                summary = validate_bundle(payload, corporate_codes=codes, now=current)
                eligible = summary["eligible"]
            except Exception as error:
                _error(st, error)
    else:
        st.caption("가져오기·저장본 조회 전에 기업·상장시장을 확인해 주세요.")
    if payload and not eligible:
        st.caption("저장 조건: 기업 일치, 7일 이내 수집, 조회 실패 없이 요청 완료, 수집 보고서 1개 이상.")
    if st.button("개인 근거로 가져오기 (점수 유지)", key=prefix + "_import", disabled=not eligible):
        try:
            result = store_factory(owner).insert_bundle(payload, ticker=ticker, owner_scope=owner,
                                                        corporate_codes=codes, now=current)
            st.success("개인 근거 저장 완료 · 기존 점수 유지" if result["inserted"] else "이미 저장된 동일 자료입니다 · 기존 점수 유지")
        except Exception as error:
            _error(st, error)
    st.markdown("**개인 저장 근거 조회**")
    st.caption("저장 당시 요청한 연도·보고서 조합과 같은 범위를 선택합니다.")
    options = [f"{y}:{c}" for y in range(current.year, current.year - 7, -1) for c in LABELS]
    defaults = [f"{r['year']}:{r['report_code']}" for r in payload["requested_reports"]] if payload else []
    options = list(dict.fromkeys(options + defaults))
    file_key = summary["sha256"][:12] if payload else "none"
    selected = st.multiselect("조회할 보고기간", options, default=defaults,
                             format_func=lambda x: x.split(":")[0] + "년 " + LABELS[x.split(":")[1]],
                             key=prefix + "_scope_" + file_key)
    scope = [{"year": x.split(":")[0], "report_code": x.split(":")[1]} for x in selected]
    result_key = prefix + "_stored_" + sha256(canonical_bytes(sorted(selected))).hexdigest()[:12]
    if st.button("같은 범위의 저장 근거 조회", key=prefix + "_load", disabled=not codes or not scope or len(scope) > 25):
        st.session_state.pop(result_key, None)
        try:
            st.session_state[result_key] = store_factory(owner).load_latest(ticker, requested_reports=scope,
                owner_scope=owner, corporate_codes=codes, now=current)
            if st.session_state[result_key] is None:
                st.info("이 종목·보고기간에 맞는 7일 이내 저장 근거가 없습니다.")
        except Exception as error:
            _error(st, error)
    stored = st.session_state.get(result_key)
    if stored and codes:
        try:
            fresh = validate_bundle(stored["payload"], corporate_codes=codes, now=current)
            if fresh["eligible"]:
                st.caption("개인 저장 근거 · 화면 재실행만으로 서버를 다시 조회하지 않습니다.")
                _show(st, stored["payload"], fresh, fin_meta, extract_metrics, current)
            else:
                st.info("저장 근거의 유효기간이 지났습니다. 새 자료를 확인해 주세요.")
        except Exception as error:
            _error(st, error)
