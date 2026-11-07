"""Read-only MSFT business context; render collected evidence without requests."""

from datetime import date, datetime, timedelta
import math
from zoneinfo import ZoneInfo

from stock_lab_core.msft_ir_review import source_identity, _quarter_end
from stock_lab_core.report_build import register_loaded_source

register_loaded_source(__name__, __file__)


def usable_packet(packet, now):
    """Fresh retrieval of a dated quarterly release, never a current-price cause."""
    try:
        year, quarter = packet['fiscal_year'], packet['fiscal_quarter']
        end = _quarter_end(year, quarter)
        published = date.fromisoformat(packet['release_date'])
        checked = datetime.fromisoformat(packet['checked_at'])
        return (now.tzinfo is not None and checked.tzinfo is not None
                and timedelta(0) <= now - checked <= timedelta(days=1)
                and end <= published <= now.astimezone(ZoneInfo('America/New_York')).date()
                and 0 <= (now.astimezone(ZoneInfo('America/New_York')).date() - published).days <= 150
                and packet['period_end'] == end.isoformat()
                and packet['period_start'] == date(end.year, end.month - 2, 1).isoformat()
                and packet.get('ticker') == 'MSFT' and packet.get('cik') == '0000789019'
                and packet.get('review_only') is True and packet.get('eligible_for_scoring') is False
                and packet.get('status') in {'confirmed', 'partial'}
                and source_identity(packet.get('source_url')) == ('release', year, quarter))
    except (KeyError, TypeError, ValueError, AttributeError):
        return False


def msft_business_lines(context, now, summary_rows=None):
    payload = context.get('msft_business_evidence')
    if payload is None:
        return []
    packet = payload.get('packet') or {}
    lines = ['', '## MSFT 사업·투자 점검', '']
    if not usable_packet(packet, now):
        return lines + ['공식 실적·전망의 날짜 또는 수집 확인이 부족해 해석을 보류합니다. 자료 부재나 매수 금지를 뜻하지 않습니다.', '']
    year, q = packet['fiscal_year'], packet['fiscal_quarter']
    actual_period = f"FY{year}Q{q} · {packet['period_end']} 종료"
    next_q, next_year = q % 4 + 1, year + (q == 4)
    forward_period = f"FY{next_year}Q{next_q} · {_quarter_end(next_year, next_q).isoformat()} 종료 예상"
    def metric(key, unit, scope, *, forward=False):
        matches = [m for m in packet.get('metrics', []) if m.get('key') == key]
        if len(matches) != 1:
            return None
        m = matches[0]
        value = m.get('value')
        expected_source = 'release' if key in {'cloud_revenue', 'azure_growth'} else 'call'
        if (isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value)
                or value < 0 or m.get('status') != 'confirmed' or m.get('unit') != unit
                or m.get('kind') != ('management_outlook' if forward else 'reported_actual')
                or m.get('period') != (forward_period if forward else actual_period)
                or m.get('scope') != scope or m.get('operator') != ('gt' if forward else 'eq')
                or source_identity(m.get('source_url')) != (expected_source, year, q)):
            return None
        return value
    cloud = metric('cloud_revenue', 'USD_billion', 'overlapping_cloud_metric')
    azure = metric('azure_growth', 'percent_yoy', 'product_metric')
    ocf = metric('ocf', 'USD_billion', 'company_total')
    cash = metric('cash_ppe', 'USD_billion', 'cash_ppe')
    outlook = metric('next_capex', 'USD_billion', 'company_reported_capex_not_cash_ppe', forward=True)
    release = f"[Microsoft 공식 실적]({packet['source_url']})"
    call_url = next((m['source_url'] for m in packet.get('metrics', [])
                     if source_identity(m.get('source_url')) == ('call', year, q)), '')
    call = f"[Microsoft 실적 설명회]({call_url})" if call_url else release
    age = (now.astimezone(ZoneInfo('Asia/Seoul')).date() - date.fromisoformat(packet['release_date'])).days
    lines += [f"**사업 배경 · 발표 {packet['release_date']}({age}일 경과), {actual_period}.** "
              '오늘의 등락 원인과 분리해 읽습니다. 실현 실적과 회사 전망을 구분하며 컨센서스 대비 평가는 미연결입니다.', '']
    if cloud is not None and azure is not None:
        lines += [f"**수요를 읽는 근거.** 사실: Microsoft Cloud 매출 {cloud:g}십억 달러, Azure 매출 전년 대비 {azure:+g}%입니다. "
                  f"해석(추정): 클라우드 사업 규모와 성장률은 고객 수요를 점검하는 근거입니다. AI만의 매출·수익성이나 투자 회수 성공을 뜻하지는 않습니다. {release}", '']
    else:
        lines += ['**수요 해석 보류.** Cloud 매출 또는 Azure 증가율의 동일 분기 근거가 부족합니다.', '']
    if cash is not None and ocf is not None:
        burden = '영업현금흐름을 넘습니다' if cash > ocf else '영업현금흐름 범위 안입니다'
        lines += [f"**성장과 현금 부담을 함께 봅니다.** 사실: 영업현금흐름 {ocf:g}십억 달러에 현금 유형자산 지출 {cash:g}십억 달러로, "
                  f"이번 분기 현금 투자는 {burden}. 해석(추정): 매출 확대와 별개로 투자 후 현금 여력이 이어지는지 확인해야 합니다. "
                  f"이 두 값만으로 현금 고갈 시점·적정가를 계산하지 않습니다. {call}", '']
    else:
        lines += ['**현금 부담 판단 보류.** 동일 분기의 영업현금흐름·현금 유형자산 지출이 모두 확인되지 않았습니다.', '']
    if outlook is not None and now.astimezone(ZoneInfo('America/New_York')).date() > _quarter_end(next_year, next_q):
        lines += ['**투자 전망 대상기간 종료.** 발표 당시 다음 분기의 전망입니다. 새 실적 원문으로 실제 집행을 확인하기 전에는 현재 전망으로 사용하지 않습니다.', '']
    elif outlook is not None:
        lines += [f"**다음 분기 투자 전망.** 회사 전망: {forward_period}, CAPEX {outlook:g}십억 달러 초과. "
                  f"해석(추정): 공급업체에는 잠재 수요지만 실제 발주·인도와 매출 전환이 확인되어야 합니다. "
                  f"이 회사 발표 CAPEX는 현금 유형자산 지출과 정의가 달라 위 수치와 직접 증감 비교하지 않습니다. {call}", '']
    else:
        lines += ['**회사 투자 전망 미확인.** 다음 분기 금액·기간·정의가 검증되지 않아 이전 전망이나 예상치로 채우지 않습니다.', '']
    from stock_lab_core.report_brief import _holding_links
    from stock_lab_core.report_evidence import records, is_held, _cell
    held = [row for row in records(summary_rows) if is_held(row)]
    links = _holding_links(held, 'Microsoft MSFT 클라우드 AI 투자 반도체', ['MSFT'], '반도체·AI', 'US')
    lines += [f"**보유 연결 · 검토 관점:** {_cell(links)}. 업종 노출을 통한 조건부 연결이며 실제 수주·손익 기여도나 매매 신호는 아닙니다.", '',
              '**다음 실적에서 해석을 바꿀 관측**', '',
              '확인할 것 | 왜 중요한가 · 반대 관측', '--- | ---',
              'Azure 성장과 고객 매출 | 성장 유지와 투자 후 매출 전환을 함께 확인. 성장 둔화가 확인되면 수요 기대를 재검토',
              '영업현금흐름과 현금 투자 | 같은 분기·같은 정의로 비교. 현금 유입보다 지출이 커지면 회수 부담 재검토',
              'CAPEX 집행·리스·장비 인도 | 전망이 실제 발주와 인도로 이어지는지 확인. 금융 방식 변경과 실제 수요 축소를 구분', '',
              f"확인할 원문: {release} · {call}. 위 관측은 검토 질문이며 기존 점수·판정에 가감하지 않습니다.", '']
    return lines
