"""Scoped report layout; retain Markdown for safe links and file exports."""

from stock_lab_core.report_build import register_loaded_source

register_loaded_source(__name__, __file__)

REPORT_STYLE = """
<style>
.st-key-market_report_reading table {
    display: block;
    width: 100%;
    overflow-x: auto;
}
.st-key-market_report_reading th { white-space: nowrap; }
.st-key-market_report_reading td {
    min-width: 5rem;
    max-width: 36rem;
    word-break: keep-all;
    overflow-wrap: break-word;
}
</style>
"""


def render_market_report(report):
    import streamlit as st

    st.markdown(REPORT_STYLE, unsafe_allow_html=True)
    with st.container(key="market_report_reading"):
        st.markdown(report)
