# AI Agent Guide for my-stock-lab

## Purpose
This repository is a Streamlit-based stock dashboard and portfolio analysis app for Korean and US markets.
It uses the `stock_lab_core` package for business logic, data formatting, and portfolio calculations.

## Key entrypoints
- `app.py` — main Streamlit application with full authentication, portfolio, holdings, dividends, macro analysis, and custom stock/ETF workflows.
- `app_sam.py` — alternate Streamlit dashboard focused on public spreadsheet-driven analysis.
- `demo_app.py` — lightweight public demo entrypoint that imports `app`.

## Run / setup
- Install dependencies:
  - `pip install -r requirements.txt`
- Run the main app:
  - `streamlit run app.py`
- Public demo:
  - `streamlit run demo_app.py`

## Architecture summary
- `app.py` is the primary UI layer; it imports helpers from `stock_lab_core`.
- `stock_lab_core/` contains reusable logic:
  - `config.py` for constants and column definitions
  - `formatters.py` for sanitizing and formatting values
  - `news.py` for analyst/news rendering helpers
  - `money_flow.py` for money flow calculations
  - `kr_etf_data.py` for ETF dataset loading and tag generation
  - `prices.py` for price fetching and cache helpers
  - `portfolio.py` for portfolio summary, weights, and reserve calculations
  - `backup.py` for recovery and backup utilities
- Local data file:
  - `stock_lab_core/data/kr_etf_lab.csv`

## Important details for AI agents
- This repo is Python-based and uses Streamlit heavily.
- There is no top-level README; use `requirements.txt` and source files to infer behavior.
- The repo expects secrets and credentials through Streamlit secrets for Google login, Supabase, and service accounts.
- `call_llm_analysis()` in `app.py` is currently a placeholder that returns the prompt string.
  - This means there is no live LLM API integration in the current repository.

## Useful patterns
- Prefer editing `stock_lab_core` helpers when logic should apply across app and demo variants.
- Keep UI changes in `app.py` / `app_sam.py`; those files combine Streamlit state, layout, and data display.
- Be careful with Korean text and labels; much of the UI and prompts are written in Korean.

## What to inspect first
1. `app.py` — main app logic, authentication, and Streamlit workflows.
2. `stock_lab_core/config.py` — shared constants and expected DataFrame schema.
3. `stock_lab_core/formatters.py` — normalization and sanitization utilities.
4. `stock_lab_core/prices.py` — external price loading, caching, and ticker normalization.

## Agent guidance
- Focus on concise, practical code fixes and enhancements.
- Avoid speculative feature additions unless the user explicitly requests them.
- Preserve Korean UI text and data semantics when editing app behavior.
- When asked to improve AI-related behavior, note that the current LLM hook is stubbed.

## Gemini-specific note
This file is intended for Gemini/Copilot-style AI agents. Use the repo structure and run commands here to stay aligned with the user’s environment.
