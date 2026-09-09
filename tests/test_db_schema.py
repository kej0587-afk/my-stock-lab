from stock_lab_core.db_schema import get_feedback_create_sql, get_swing_radar_create_sql


def test_swing_radar_sql_contains_rls_and_primary_key():
    sql = get_swing_radar_create_sql()
    assert "create table if not exists swing_radar" in sql
    assert "primary key (owner_email, ticker)" in sql
    assert "enable row level security" in sql


def test_feedback_sql_contains_indexes_and_rls():
    sql = get_feedback_create_sql()
    assert "create table if not exists feedback" in sql
    assert "feedback_owner_email_idx" in sql
    assert "feedback_created_at_idx" in sql
    assert "enable row level security" in sql
