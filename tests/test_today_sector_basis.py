import pandas as pd
from stock_lab_core.today_sector_basis import sector_observation_basis


def test_old_or_mixed_us_source_does_not_become_current_sector_leader():
    snapshot = {
        'flow_df': pd.DataFrame({'Ticker':['005930.KS','XLF'], '기준일':['2026-11-27','2026-11-25']}),
        'theme_flow_df': pd.DataFrame({'Ticker':['MSFT','GOOGL'], '기준일':['2026-11-27','2026-11-25']}),
        'sector_ability_cards': [{'market':'한국','rank':1,'title':'한국 선두'},
                                 {'market':'미국','rank':1,'title':'미국 선두'}],
    }
    dates = {'KR':'2026-11-27','US':'2026-11-27'}
    rows, leaders = sector_observation_basis(snapshot, dates)
    assert leaders == {'한국':'한국 선두'}
    assert rows[-1]['가격 기준일'] == '2026-11-25 ~ 2026-11-27'
    snapshot['flow_df'].loc[1, '기준일'] = '2026-11-27'
    snapshot['theme_flow_df']['기준일'] = '2026-11-27'
    assert sector_observation_basis(snapshot, dates)[1] == {'한국':'한국 선두','미국':'미국 선두'}
    snapshot['theme_flow_df'].loc[0, '기준일'] = None
    assert sector_observation_basis(snapshot, dates)[1] == {'한국':'한국 선두'}
    assert snapshot['sector_ability_cards'][1]['title'] == '미국 선두'


def test_missing_source_is_unknown_not_current():
    assert sector_observation_basis({}, {'US':'2026-11-27','KR':'2026-11-27'}) == ([], {})
