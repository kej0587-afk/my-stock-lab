"""Keep the existing 30s cache outside the miss timer; no policy/query changes."""
import ast
from pathlib import Path
import subprocess


def test_financial_read_body_and_cache_contract_are_unchanged():
    sources=[subprocess.check_output(['git','show','13d83bd1:app.py']).decode('utf8'),
             Path('app.py').read_text('utf-8-sig')]
    trees=[ast.parse(s) for s in sources]
    for name in ('load_fin_scores_db_for_user','load_fin_scores_db'):
        old,new=[next(n for n in t.body if isinstance(n,ast.FunctionDef) and n.name==name) for t in trees]
        assert ast.dump(old.args)==ast.dump(new.args)
        assert ast.dump(ast.Module(body=old.body,type_ignores=[]))==ast.dump(ast.Module(body=new.body,type_ignores=[]))
        timer=new.decorator_list[-1]
        expected="timed_call('external_data', 'financial_scores_db_miss')" if name.endswith('for_user') else "timed_call('display', 'financial_scores_cache_read')"
        assert ast.unparse(timer)==expected
        assert [ast.dump(n) for n in new.decorator_list[:-1]]==[ast.dump(n) for n in old.decorator_list]
        if name.endswith('for_user'):
            assert ast.unparse(new.decorator_list[0])=='st.cache_data(ttl=30, show_spinner=False)'
