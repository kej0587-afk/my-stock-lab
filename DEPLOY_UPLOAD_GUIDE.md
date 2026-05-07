# Stock Lab 배포 업로드 가이드

Streamlit Cloud/GitHub에는 앱 실행에 필요한 파일만 올리면 됩니다.

## 꼭 올릴 것

- `app.py`
- `requirements.txt`
- `stock_lab_core/`
  - `__init__.py`
  - `backup.py`
  - `config.py`
  - `formatters.py`
  - `kr_etf_data.py`
  - `money_flow.py`
  - `news.py`
  - `portfolio.py`
  - `prices.py`
  - `data/kr_etf_lab.csv`
- `.gitignore`
- 필요하면 문서 파일: `DEPLOY_UPLOAD_GUIDE.md`, `STOCK_LAB_USER_MANUAL.md`

## 올리면 안 되는 것

- `.venv311/`, `.venv/`, `venv/`
- `__pycache__/`
- `*.pyc`
- `app.py.bak*`
- `app_backup_*.py`
- `stock_lab_backup_*.zip`
- `logs-*.txt`
- `.streamlit/secrets.toml`
- API 키, 비밀번호, Supabase service role key가 들어간 파일

## GitHub 웹에서 수동 업로드할 때

1. `app.py`를 교체합니다.
2. `requirements.txt`를 교체합니다.
3. `stock_lab_core` 폴더를 통째로 올립니다.
4. 단, `stock_lab_core/__pycache__`와 `backup_before` 파일은 빼도 됩니다.
5. Secrets 값은 GitHub에 올리지 말고 Streamlit Cloud의 `Manage app -> Settings -> Secrets`에만 입력합니다.

## Streamlit Cloud에 꼭 필요한 Secrets

앱 설정에 따라 다르지만 보통 아래 값이 필요합니다.

- `AUTH_MODE`
- `ALLOWED_EMAILS`
- `ADMIN_EMAILS`
- `APP_PASSWORD` 또는 Google OAuth 관련 `[auth]` 설정
- `SUPABASE_URL`
- `SUPABASE_SERVICE_ROLE_KEY`
- `dart_api_key`
- `fmp_api_key`

`secrets.toml` 파일 자체를 GitHub에 올리면 안 됩니다.
