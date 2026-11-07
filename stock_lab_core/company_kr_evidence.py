"""Read-only Korean company evidence fallback; no scoring, writes or cache."""
from datetime import datetime, timezone

from stock_lab_core.dart_evidence import require, stamp, validate_bundle
from stock_lab_core.dart_evidence_preview import coverage_rows, metric_rows, verified_codes
from stock_lab_core.financial_review import build_financial_review
from stock_lab_core.report_build import register_loaded_source

register_loaded_source(__name__, __file__)


def load_company_kr_evidence(ticker, *, owner, load_live, identity_loader=None,
                             store_factory=None, extract_metrics=None, now=None):
    """Explicit single-company query. Stored evidence is used only on failure."""
    current = now or datetime.now(timezone.utc)
    try:
        financials = load_live(ticker)
        packet = build_financial_review({}, financials, checked_at=current.isoformat())
        if isinstance(financials, dict) and financials.get('ok'):
            return packet
    except Exception:
        # Provider exceptions may contain credentials/URLs. Never serialize them.
        packet = build_financial_review({}, {'ok': False, 'source': 'dart',
            'reason': 'DART 전송 실패'}, checked_at=current.isoformat())
    if not (owner and identity_loader and store_factory and extract_metrics):
        return packet
    try:
        identity = identity_loader(ticker)
        current = now or datetime.now(timezone.utc)
        codes = verified_codes(identity, ticker, current)
        require(bool(codes), 'identity_map_required')
        stored = store_factory(owner).load_recent(ticker, owner_scope=owner,
                                                   corporate_codes=codes, now=current)
        if stored is None:
            packet['저장 근거 상태'] = '이 종목의 7일 이내 개인 저장 근거 없음 · 정밀관측소에서 DART 파일 가져오기 후 다시 조회하세요.'
            return packet
        payload = stored['payload']
        require(payload['ticker'] == ticker, 'selected_ticker_mismatch')
        summary = validate_bundle(payload, corporate_codes=codes, now=current)
        require(summary['eligible'], 'evidence_not_eligible')
        rows = metric_rows(payload, extract_metrics)
        coverage = coverage_rows(payload)
        collected = stamp(payload['collected_at'])
        packet.update({
            '조회 상태': '개인 저장 DART 근거 연결 · 실시간 조회 실패 · 기존 점수 유지',
            '공급처': 'DART 로컬 수집·업로드 (원문 서명 미검증)',
            '공급처 조회 기간': ' / '.join(f"{r['사업연도']}년 {r['보고서']}" for r in coverage),
            '원자료': rows, '수집 범위': coverage,
            '저장 근거': {'ticker': ticker, 'corp_code': payload['corp_code'],
                'collected_at': payload['collected_at'], 'imported_at': stored['imported_at'],
                'age_hours': round(max(0, (current-collected).total_seconds())/3600, 1),
                'freshness': summary['freshness'], 'sha256': summary['sha256']},
            '저장 근거 상태': '최근 수집은 최신 실적 발표 전체 반영을 뜻하지 않습니다. 저장 당시 요청한 보고기간만 표시합니다.',
        })
    except Exception as error:
        code = str(error)
        if code in {'identity_map_required', 'identity_expired', 'listing_unavailable_or_mismatch'}:
            reason = '기업코드·상장시장 확인 실패'
        elif code == 'schema_unavailable':
            reason = '개인 근거 저장 테이블 미연결'
        elif code == 'store_unavailable':
            reason = '개인 저장소 조회 실패'
        else:
            reason = '기업·자료 형식·유효기간 검증 실패'
        packet['저장 근거 상태'] = reason + ' · 검증되지 않은 저장 자료는 표시하지 않습니다.'
    return packet
