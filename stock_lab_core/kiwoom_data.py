"""Opt-in Kiwoom domestic market data; no accounts, holdings, orders or news.

Only au10001 and ka10001 are allowed. Callers supply a secrets mapping; this
module never imports Streamlit or reads credentials from disk/environment.
See docs/maintenance/20261012_kiwoom_setup.md for the verified API contract.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
import math
import re
import threading
import time
from typing import Any

import requests


_BASE_URLS = {"real": "https://api.kiwoom.com", "mock": "https://mockapi.kiwoom.com"}
_TOKEN_PATH = "/oauth2/token"
_INFO_PATH = "/api/dostk/stkinfo"
_SOURCE_URL = "https://openapi.kiwoom.com/guide/apiguide"
_KST = timezone(timedelta(hours=9))
_REFRESH_MARGIN_SECONDS = 60
_CONFIG_REASONS = {
    "disabled": "Kiwoom data is disabled.",
    "missing_configuration": "Both kiwoom.appkey and kiwoom.secretkey are required.",
    "invalid_configuration": "Invalid Kiwoom configuration; check the setup guide.",
}


def _number(value: Any) -> float | None:
    if isinstance(value, bool) or not isinstance(value, (str, int, float)):
        return None
    try:
        number = float(value.strip().replace(",", "") if isinstance(value, str) else value)
        return number if math.isfinite(number) else None
    except (TypeError, ValueError, OverflowError):
        return None


def _code(ticker: Any) -> str:
    if not isinstance(ticker, str):
        return ""
    symbol = ticker.strip().upper()
    if not re.fullmatch(r"[0-9][A-Z0-9]{5}(?:\.(?:KS|KQ))?", symbol):
        return ""
    code = symbol.split(".")[0]
    return code if code != "000000" else ""


def _return_code(payload: Mapping) -> int | None:
    value = payload.get("return_code")
    if type(value) is int:
        return value
    if isinstance(value, str) and re.fullmatch(r"-?[0-9]{1,8}", value.strip()):
        return int(value)
    return None


@dataclass(frozen=True)
class KiwoomConfig:
    enabled: bool = False
    appkey: str = field(default="", repr=False)
    secretkey: str = field(default="", repr=False)
    environment: str = "real"
    connect_timeout: float = 3.05
    read_timeout: float = 10.0
    _error: str = field(default="", repr=False)

    @property
    def status(self) -> str:
        if self._error:
            return self._error
        if type(self.enabled) is not bool:
            return "invalid_configuration"
        if not self.enabled:
            return "disabled"
        if not isinstance(self.environment, str) or self.environment not in _BASE_URLS:
            return "invalid_configuration"
        for value in (self.connect_timeout, self.read_timeout):
            if type(value) not in (float, int) or not math.isfinite(value) or not 0 < value <= 60:
                return "invalid_configuration"
        for value in (self.appkey, self.secretkey):
            if not isinstance(value, str) or not value.strip():
                return "missing_configuration"
            if value != value.strip() or any(char.isspace() for char in value):
                return "invalid_configuration"
        return "ready"


def kiwoom_client_from_secrets(secrets: Mapping | None = None) -> KiwoomDataClient:
    """Build from the full ``st.secrets`` mapping, without any network request.

    ``None`` / missing section means disabled. Only literal TOML ``enabled =
    true`` enables requests. Malformed/unavailable configuration fails closed.
    Retain this client with st.cache_resource to reuse its in-memory token.
    """
    try:
        section = {} if secrets is None else secrets.get("kiwoom", {})
        if not isinstance(section, Mapping):
            config = KiwoomConfig(_error="invalid_configuration")
        elif section.get("enabled", False) is False:
            config = KiwoomConfig()
        else:
            config = KiwoomConfig(
                enabled=section.get("enabled"),
                appkey=section.get("appkey", ""),
                secretkey=section.get("secretkey", ""),
                environment=section.get("environment", "real"),
                connect_timeout=section.get("connect_timeout", 3.05),
                read_timeout=section.get("read_timeout", 10.0),
            )
    except (FileNotFoundError, KeyError):
        config = KiwoomConfig()
    except Exception:
        # Secrets providers may raise errors containing private file paths.
        config = KiwoomConfig(_error="invalid_configuration")
    return KiwoomDataClient(config)


def _snapshot(ticker: str, environment: str, status: str, reason: str = "") -> dict:
    return {
        "ok": False, "status": status, "reason": reason,
        "symbol": _code(ticker), "market": "KR", "currency": "KRW",
        "source": "Kiwoom REST ka10001", "source_url": _SOURCE_URL,
        "api_id": "ka10001", "environment": environment,
        "is_mock": environment == "mock", "asof": "", "fetched_at": "",
        "http_status": None, "provider_code": None, "data": {},
    }


def normalize_kiwoom_domestic_snapshot(
    payload: Mapping, ticker: str, *, fetched_at: str = "", environment: str = "real"
) -> dict:
    """Normalize ka10001 without I/O; missing values remain None, never zero.

    Monetary totals documented in KRW 100 million are converted to KRW.
    PER/PBR/EPS/BPS/ROE retain provider scale and unspecified reporting period.
    No target, consensus count, news, quote timestamp or financial date is inferred.
    """
    snapshot = _snapshot(ticker, environment, "invalid_response", "Invalid stock response.")
    snapshot["fetched_at"] = fetched_at
    if not snapshot["symbol"] or not isinstance(payload, Mapping):
        return snapshot
    result_code = _return_code(payload)
    snapshot["provider_code"] = result_code
    if result_code != 0:
        snapshot.update(status="api_error" if result_code is not None else "invalid_response")
        return snapshot
    # Do not attach a valid-looking quote belonging to a different instrument.
    returned_code = payload.get("stk_cd")
    if returned_code not in (None, "") and returned_code != snapshot["symbol"]:
        snapshot["reason"] = "Response symbol does not match the requested KRX symbol."
        return snapshot

    data = {"symbol": snapshot["symbol"], "currency": "KRW"}
    name = payload.get("stk_nm")
    data["shortName"] = name.strip()[:80] if isinstance(name, str) and name.strip() else None
    for target, source in {
        "currentPrice": "cur_prc", "open": "open_pric",
        "dayHigh": "high_pric", "dayLow": "low_pric",
    }.items():
        number = _number(payload.get(source))
        # Signs on Kiwoom price levels encode direction, not negative prices.
        data[target] = abs(number) if number is not None and number != 0 else None
    for target, source in {
        "priceChange": "pred_pre", "priceChangePercent": "flu_rt",
        "per": "per", "pbr": "pbr", "eps": "eps", "bps": "bps", "roe": "roe",
    }.items():
        data[target] = _number(payload.get(source))
    for target, source in {
        "marketCap": "mac", "revenue": "sale_amt",
        "operatingIncome": "bus_pro", "netIncome": "cup_nga",
    }.items():
        number = _number(payload.get(source))
        scaled = number * 100_000_000 if number is not None else None
        data[target] = scaled if scaled is not None and math.isfinite(scaled) else None
    if data["marketCap"] is not None and data["marketCap"] <= 0:
        data["marketCap"] = None
    volume = _number(payload.get("trde_qty"))
    data["volume"] = int(volume) if volume is not None and volume >= 0 and volume.is_integer() else None
    usable = any(value is not None for key, value in data.items() if key not in {"symbol", "currency", "shortName"})
    snapshot.update(
        ok=usable, status="available" if usable else "no_data",
        reason="" if usable else "No usable numeric stock data in response.", data=data,
    )
    return snapshot


class _KiwoomError(Exception):
    def __init__(self, status: str, reason: str, *, http_status=None, provider_code=None):
        super().__init__(reason)
        self.status = status
        self.http_status = http_status
        self.provider_code = provider_code


class KiwoomDataClient:
    """Thread-safe, single-process client with no automatic retries.

    One snapshot costs at most one token issuance and one ka10001 request.
    ``session`` and ``now`` are dependency-injection hooks for offline tests.
    Do not expose this object, its config or HTTP internals in the UI/logs.
    """

    def __init__(
        self, config: KiwoomConfig | None = None, *,
        session: Any = None, now: Callable[[], float] = time.time,
    ):
        self._config = config if config is not None else KiwoomConfig()
        self._session = session if session is not None else requests.Session()
        if session is None:
            # No implicit .netrc credentials/proxies, redirects, or retries.
            self._session.trust_env = False
            self._session.mount("https://", requests.adapters.HTTPAdapter(max_retries=0))
        self._now = now
        self._lock = threading.Lock()
        self._token = ""
        self._expires_at = 0.0

    @property
    def status(self) -> str:
        return self._config.status

    def _post(self, path: str, api_id: str, body: dict, *, token: str = "") -> dict:
        if (path, api_id) not in {(_TOKEN_PATH, "au10001"), (_INFO_PATH, "ka10001")}:
            raise _KiwoomError("unsupported_endpoint", "Only token and domestic basic data are allowed.")
        headers = {"Content-Type": "application/json;charset=UTF-8", "api-id": api_id}
        if token:
            headers["authorization"] = f"Bearer {token}"
        try:
            response = self._session.post(
                _BASE_URLS[self._config.environment] + path, json=body, headers=headers,
                timeout=(self._config.connect_timeout, self._config.read_timeout),
                allow_redirects=False,
            )
        except requests.Timeout:
            raise _KiwoomError("timeout", "Kiwoom request timed out.") from None
        except requests.RequestException:
            raise _KiwoomError("network_error", "Kiwoom network request failed.") from None
        try:
            status = response.status_code
            if status != 200:
                label = "rate_limited" if status == 429 else "auth_error" if status in (401, 403) else "http_error"
                raise _KiwoomError(label, "Kiwoom HTTP request was rejected.", http_status=status)
            try:
                payload = response.json()
            except ValueError:
                raise _KiwoomError("invalid_response", "Kiwoom returned invalid JSON.", http_status=status) from None
            if not isinstance(payload, dict) or _return_code(payload) is None:
                raise _KiwoomError("invalid_response", "Kiwoom response has no valid result code.", http_status=status)
            code = _return_code(payload)
            if code != 0:
                label = "rate_limited" if code == 1700 else "auth_error" if 8000 <= code < 8100 else "api_error"
                raise _KiwoomError(label, "Kiwoom rejected the API request.", http_status=status, provider_code=code)
            return payload
        finally:
            response.close()

    def _access_token(self) -> str:
        if self._token and self._now() < self._expires_at - _REFRESH_MARGIN_SECONDS:
            return self._token
        self._token, self._expires_at = "", 0.0
        payload = self._post(_TOKEN_PATH, "au10001", {
            "grant_type": "client_credentials", "appkey": self._config.appkey,
            "secretkey": self._config.secretkey,
        })
        token, token_type, expiry = (payload.get(key) for key in ("token", "token_type", "expires_dt"))
        if not isinstance(token, str) or not token or any(char.isspace() for char in token):
            raise _KiwoomError("invalid_response", "Invalid token response.")
        if not isinstance(token_type, str) or token_type.lower() != "bearer":
            raise _KiwoomError("invalid_response", "Invalid token type.")
        if not isinstance(expiry, str) or not re.fullmatch(r"[0-9]{14}", expiry):
            raise _KiwoomError("invalid_response", "Invalid token expiry.")
        try:
            expires_at = datetime.strptime(expiry, "%Y%m%d%H%M%S").replace(tzinfo=_KST).timestamp()
        except ValueError:
            raise _KiwoomError("invalid_response", "Invalid token expiry.") from None
        if expires_at <= self._now() + _REFRESH_MARGIN_SECONDS:
            raise _KiwoomError("auth_error", "Token is expired or too close to expiry.")
        self._token, self._expires_at = token, expires_at
        return token

    def get_domestic_snapshot(self, ticker: str) -> dict:
        """Read one six-character KRX code (optional .KS/.KQ), never holdings.

        US tickers, NXT/SOR suffixes and malformed tickers fail before any I/O.
        Failed requests return sanitized metadata and empty data. Callers must
        separately check currentPrice before using a partially available result.
        """
        environment = self._config.environment if self._config.environment in ("real", "mock") else ""
        snapshot = _snapshot(ticker, environment, self.status)
        if self.status != "ready":
            snapshot["reason"] = _CONFIG_REASONS[self.status]
            return snapshot
        code = _code(ticker)
        if not code:
            snapshot.update(status="unsupported_ticker", reason="A six-character KRX stock code is required.")
            return snapshot
        # Serialize refresh and Session use; waiting callers also have a bound.
        if not self._lock.acquire(timeout=self._config.connect_timeout + self._config.read_timeout + 1):
            snapshot.update(status="busy", reason="Another Kiwoom request is still running.")
            return snapshot
        try:
            payload = self._post(_INFO_PATH, "ka10001", {"stk_cd": code}, token=self._access_token())
            fetched_at = datetime.fromtimestamp(self._now(), timezone.utc).isoformat()
            snapshot = normalize_kiwoom_domestic_snapshot(payload, code, fetched_at=fetched_at, environment=environment)
            snapshot["http_status"] = 200
        except _KiwoomError as exc:
            if exc.status == "auth_error":
                self._token, self._expires_at = "", 0.0
            snapshot.update(status=exc.status, reason=str(exc), http_status=exc.http_status, provider_code=exc.provider_code)
        finally:
            self._lock.release()
        return snapshot
