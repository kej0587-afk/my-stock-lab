from copy import deepcopy
from unittest.mock import Mock
import ast
from pathlib import Path

import pandas as pd
import pytest

from stock_lab_core.sector_display_snapshot import prepare_sector_display


def test_two_surfaces_share_final_command_and_cards_without_second_lookup():
    source = pd.DataFrame({'Ticker':['X'],'1D':[.01]})
    snapshot = {'sector_rotation_df':source, 'command_flow_df':pd.DataFrame({'old':[1]})}
    before = deepcopy(snapshot)
    unified, command = pd.DataFrame({'final':[1]}), pd.DataFrame({'prepared':[2]})
    cards = [{'market':'미국','rank':1,'title':'동일 선두','total':7.1}]
    unify, prepare, build = Mock(return_value=unified), Mock(return_value=command), Mock(return_value=cards)
    args = dict(unify=unify,prepare=prepare,build_cards=build)
    top = prepare_sector_display(snapshot, {'mode':'위험'}, allow_prepare=True, **args)
    # The existing lower panel publishes its command frame after rendering.
    snapshot['command_flow_df'] = top[1]
    lower = prepare_sector_display(snapshot, {'mode':'위험'}, **args)
    assert top[0] is lower[0] and top[1] is lower[1] and top[2] is lower[2]
    assert top[2][0]['total'] == 7.1
    unify.assert_called_once(); prepare.assert_called_once(); build.assert_called_once()
    pd.testing.assert_frame_equal(source,before['sector_rotation_df'])
    # Only the existing pure display-card policy responds to guard changes.
    prepare_sector_display(snapshot, {'mode':'방어'}, **args)
    assert unify.call_count == prepare.call_count == 1 and build.call_count == 2
    snapshot['sector_rotation_df'] = pd.DataFrame({'Ticker':['X'],'1D':[.02]})
    prepare_sector_display(snapshot, {'mode':'방어'}, **args)
    assert unify.call_count == prepare.call_count == 1
    prepare_sector_display(snapshot, {'mode':'방어'}, allow_prepare=True, **args)
    assert unify.call_count == prepare.call_count == 2


def test_failed_preparation_does_not_stamp_success_or_mutate_inputs():
    frame = pd.DataFrame({'Ticker':['X']}); snapshot={'sector_rotation_df':frame}
    with pytest.raises(RuntimeError):
        prepare_sector_display(snapshot, {}, allow_prepare=True, unify=Mock(side_effect=RuntimeError),prepare=Mock(),build_cards=Mock())
    assert list(snapshot) == ['sector_rotation_df'] and snapshot['sector_rotation_df'] is frame


def test_both_app_surfaces_use_shared_preparation_and_no_independent_card_build():
    tree=ast.parse(Path('app.py').read_text(encoding='utf-8-sig'))
    for name in ('render_today_unified_briefing_panel','render_today_market_flow_panel'):
        node=next(n for n in tree.body if isinstance(n,ast.FunctionDef) and n.name==name)
        calls=[n.func.id for n in ast.walk(node) if isinstance(n,ast.Call) and isinstance(n.func,ast.Name)]
        assert calls.count('prepare_sector_display') == 1
        assert '_flow_sector_ability_cards' not in calls
