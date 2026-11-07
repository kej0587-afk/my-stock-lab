"""One report-time SEC query/cache plus a source-bound cash-burden reading."""

from copy import deepcopy
import threading
import time

from stock_lab_core.msft_cash_trend import build_msft_cash_trend, usable_cash_packet
from stock_lab_core.sec_quarter_review_view import load_quarter_evidence
from stock_lab_core.report_build import register_loaded_source

register_loaded_source(__name__, __file__)

_CACHE = {}
_LOCK = threading.Lock()
SUCCESS_TTL = 6 * 3600


def collect_msft_cash_evidence(now, *, configured, resolve_cik, fetch_facts, is_demo=False):
    if not configured or is_demo:
        return dict(packet=None, collection='not_configured')
    with _LOCK:
        packet = _CACHE.get('packet')
        if time.monotonic() - _CACHE.get('at', 0) < SUCCESS_TTL and usable_cash_packet(packet, now):
            return dict(packet=deepcopy(packet), collection='success_cache')
        try:
            packet = load_quarter_evidence('MSFT', resolve_cik=resolve_cik, fetch_facts=fetch_facts, now=now)
            trend = build_msft_cash_trend(packet, now)
            if trend['status'] != 'connected' or not any(r['valid'] for r in trend['rows']):
                return dict(packet=None, collection='unverified')
        except Exception:
            # A failed optional source must not discard the report's other context.
            # Provider bodies/credentials never enter logs or generated text.
            return dict(packet=None, collection='unavailable')
        _CACHE.update(packet=deepcopy(packet), at=time.monotonic())
        return dict(packet=packet, collection='collected')


def msft_cash_lines(context, now):
    payload = context.get('msft_cash_evidence')
    if payload is None:
        return []
    trend = build_msft_cash_trend(payload.get('packet'), now)
    lines = ['', '## MSFT 8분기 현금 부담', '']
    if not trend['rows']:
        reason = 'SEC 연락처 미설정 또는 체험모드' if payload.get('collection') == 'not_configured' else 'SEC 조회·기간·공시 검증 미완료'
        return lines + [f'{reason}로 추세 해석을 보류합니다. 빈 분기를 0이나 회사 전망으로 채우지 않습니다.', '']
    rows, comparison = trend['rows'], trend['latest_comparison']
    if comparison:
        delta = comparison['burden_delta_pp']
        direction = '커졌습니다' if delta > 0.05 else '줄었습니다' if delta < -0.05 else '표시 정밀도 내 비슷합니다'
        lines += [f"**공시 수치상 현금 투자 부담이 {direction}.** 최근 분기({comparison['current_end']})에는 영업으로 들어온 현금의 "
                  f"{comparison['current_burden']:.1f}%를 유형자산 투자에 썼습니다. 전년 동기({comparison['previous_end']}) "
                  f"{comparison['previous_burden']:.1f}%보다 {delta:+.1f}%p입니다. "
                  f"[동일 제출본의 현금흐름 공시]({comparison['source_url']})", '']
        if comparison['capex_growth_pct'] is not None:
            lines += [f"**왜 중요한가 · 해석(추정).** 같은 기간 현금 투자는 {comparison['capex_growth_pct']:+.1f}%, "
                      f"영업현금흐름은 {comparison['ocf_growth_pct']:+.1f}% 변했습니다. "
                      '투자 비율은 영업현금 중 투자에 배정하는 몫이며, 남는 현금의 절대액과 함께 봐야 합니다. '
                      f"투자 후 단순 잔여현금의 전년 동기 차이는 {comparison['residual_delta']/1e8:+,.1f}억 달러입니다. "
                      f"[계산 근거]({comparison['source_url']})", '']
    else:
        lines += ['**최신 현금 부담의 전년 동기 비교는 보류합니다.** 최신성·양의 영업현금흐름·동일 제출본/정의 조건을 모두 통과한 두 분기가 필요합니다.', '']
    comparable = trend['comparisons']
    if comparable:
        up = sum(c['burden_delta_pp'] > 0.05 for c in comparable)
        coverage = ('누락·보류 구간을 잇는 연속 추세나 8분기 전체의 개선/악화로 단정하지 않습니다.'
                    if trend['held_count'] or trend['gaps'] else
                    '이는 관측된 전년 동기 비교이며, 매 분기 연속 악화나 현금 고갈을 뜻하지 않습니다.')
        lines += [f"최근 관측 {len(rows)}분기 중 전년 동기 비교가 가능한 {len(comparable)}쌍에서는 "
                  f"{up}쌍의 투자 부담 비율이 높아졌습니다. {coverage}", '']
    lines += ['금액: 억 달러 · 비율: 현금 유형자산 지출 ÷ 영업현금흐름(양수일 때).', '',
              '분기 종료 | 영업현금흐름 | 현금 투자 | 투자 비율 | 투자 후 현금¹ | 공시·검증',
              '--- | ---: | ---: | ---: | ---: | ---']
    for row in rows:
        if not row['valid']:
            lines.append(f"{row['end']} | — | — | — | — | 제출본·누락/정의 확인 전 보류")
            continue
        ratio = f"{row['burden_pct']:.1f}%" if row['burden_pct'] is not None else '보류(영업현금≤0)'
        source_label = ('실적발표 원문 대조²' if row.get('recovery') else f"제출 {row['filed']}")
        lines.append(f"{row['end']} | {row['ocf']/1e8:,.1f} | {row['cash_capex']/1e8:,.1f} | {ratio} | "
                     f"{row['residual']/1e8:,.1f} | [{source_label}]({row['source_url']})")
    lines += ['', f"검증 보류 {trend['held_count']}분기 · 관측 분기 사이 누락 {'있음' if trend['gaps'] else '없음'}. "
              '서로 다른 제출본의 누적 차감은 재작성 여부를 확인하기 전 비율·합계·추세에 사용하지 않습니다.',
              '¹ 투자 후 현금은 영업현금흐름−현금 유형자산 지출의 단순 차이이며 현금 잔액·회사 조정 FCF가 아닙니다. '
              '비현금 리스·인수·배당·자사주 매입·차입 상환은 포함하지 않습니다. 회사 전체 공시이며 AI만의 손익은 분리되지 않습니다.', '',
              '**다음 확인:** 다음 동일 기준 분기에도 투자 비율이 올라가는지, 투자 후 현금이 줄어드는지 함께 봅니다. '
              '비율이 낮아져도 투자 취소·장비 인도 지연 때문이면 수요 회복으로 단정하지 않습니다. '
              '공시 수치 비교이며 사업범위 변경·계절성은 별도 검토합니다. 현재 주가 원인·현금 고갈 예측·점수 변경에 사용하지 않습니다.', '']
    restored = [r for r in rows if r.get('recovery')]
    if restored:
        lines += [f"² 원문 대조 복구 {len(restored)}분기: 2026-07-29 실적발표 첨부 현금흐름표의 직접 분기값(미감사)을 "
                  '연차·9개월 보고서 및 2025년 원발표와 대조했습니다. 현금 유형자산 지출만 포함하며 리스 포함 투자 전망과 다릅니다. '
                  '대조일 2026-11-08. 조회된 원금액·기간·제출본이 검증 기록과 달라지면 다시 보류합니다.', '']
    return lines
