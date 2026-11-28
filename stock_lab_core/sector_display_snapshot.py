"""Share the existing completed sector display across two Today surfaces."""
import hashlib
import json
import pandas as pd


def prepare_sector_display(snapshot, guard, *, unify, prepare, build_cards, allow_prepare=False):
    """Prepare once per source snapshot; guard changes only rebuild pure cards.

    The callbacks are the existing lower-panel builders. `unify` and `prepare`
    may supplement provider data, so run them only at an explicit refresh boundary.
    These are
    derived snapshot fields, not provider caches; TTLs and calculation inputs stay
    untouched. `command_flow_df` is published by the existing lower panel only.
    """
    frames = [snapshot.get(key, pd.DataFrame()) for key in
              ('sector_rotation_df', 'theme_rotation_df', 'subtheme_group_df')]
    source = hashlib.sha256(json.dumps([
        frame.to_json(orient='split', date_format='iso', default_handler=str)
        if isinstance(frame, pd.DataFrame) else None for frame in frames
    ], ensure_ascii=False).encode()).hexdigest()
    version = 'shared-sector-display-v1'
    saved = snapshot.get('_sector_display_prepared', {})
    if saved.get('source') != source or saved.get('version') != version:
        if not allow_prepare:
            snapshot['sector_ability_cards'] = []
            return pd.DataFrame(), pd.DataFrame(), []
        unified = unify(*frames)
        command = prepare(unified) if isinstance(unified, pd.DataFrame) and not unified.empty else pd.DataFrame()
        saved = {'source': source, 'version': version, 'unified': unified, 'command': command}
    guard_key = json.dumps(guard or {}, ensure_ascii=False, sort_keys=True, default=str)
    if saved.get('guard') != guard_key or 'cards' not in saved:
        saved['cards'] = build_cards(saved['command'], frames[0], frames[1], market_guard=guard)
        saved['guard'] = guard_key
    snapshot['_sector_display_prepared'] = saved
    snapshot['sector_ability_cards'] = saved['cards']
    snapshot['sector_cards_view_version'] = version
    return saved['unified'], saved['command'], saved['cards']
