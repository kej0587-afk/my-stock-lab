import streamlit as st
from pathlib import Path
import sqlite3
import pandas as pd

st.title("SQLite Recovery Check")

db = Path("data/portfolio.db")

st.write("DB path:", str(db.resolve()))
st.write("Exists:", db.exists())

if db.exists():
    st.write("Size:", db.stat().st_size)

    conn = sqlite3.connect(db)
    for table in ["settings", "holdings", "dividends", "monthly_logs", "fin_scores", "watchlist"]:
        st.subheader(table)
        try:
            df = pd.read_sql_query(f"select * from {table}", conn)
            st.dataframe(df)
        except Exception as e:
            st.error(f"{table}: {e}")
    conn.close()
else:
    st.error("data/portfolio.db not found")
