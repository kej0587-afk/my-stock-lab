"""DART corporate-code download with allowlisted, credential-free diagnostics."""

import io
import json
import re
from time import perf_counter
import xml.etree.ElementTree as ET
import zipfile

import requests


class CorporateCodeMap(dict):
    """Dictionary-compatible result; empty failures retain safe diagnostics."""

    def __init__(self, codes=(), *, diagnostic=None):
        super().__init__(codes)
        self.diagnostic = diagnostic or {}


def fetch_corporate_codes(api_key, *, get=requests.get, timeout=8):
    started = perf_counter()
    diagnostic = {"stage": "configuration", "cause": "missing_key", "http_status": None,
                  "api_status": None, "content_type": "unknown", "response_bytes": 0}

    def result(codes=()):
        diagnostic["elapsed_seconds"] = round(perf_counter() - started, 3)
        return CorporateCodeMap(codes, diagnostic=dict(diagnostic))

    if not api_key:
        return result()
    diagnostic.update(stage="request", cause="unknown")
    try:
        response = get("https://opendart.fss.or.kr/api/corpCode.xml",
                       params={"crtfc_key": api_key}, timeout=timeout)
        status = getattr(response, "status_code", 200)
        diagnostic["http_status"] = status if isinstance(status, int) and 100 <= status <= 599 else None
        content_type = str(getattr(response, "headers", {}).get("Content-Type", "")).split(";", 1)[0].strip().lower()
        if content_type in {"application/zip", "application/octet-stream", "application/x-zip-compressed",
                            "application/xml", "text/xml", "application/json", "text/html"}:
            diagnostic["content_type"] = content_type
        if diagnostic["http_status"] != 200:
            diagnostic.update(stage="http", cause="http_error")
            return result()
        payload = response.content
        diagnostic["response_bytes"] = len(payload)
    except requests.ConnectTimeout:
        diagnostic.update(cause="connect_timeout")
        return result()
    except requests.ReadTimeout:
        diagnostic.update(cause="read_timeout")
        return result()
    except requests.Timeout:
        diagnostic.update(cause="timeout")
        return result()
    except requests.RequestException:
        diagnostic.update(cause="transport_error")
        return result()

    diagnostic["stage"] = "decode"
    try:
        with zipfile.ZipFile(io.BytesIO(payload)) as archive:
            root = ET.fromstring(archive.read(archive.namelist()[0]))
    except (zipfile.BadZipFile, IndexError, KeyError, ET.ParseError, RuntimeError):
        # Provider errors may be XML/JSON rather than the documented ZIP. Never
        # retain message, response body, request URL, headers or exception text.
        code = None
        if len(payload) <= 65536:
            try:
                code = ET.fromstring(payload).findtext("status")
            except ET.ParseError:
                try:
                    data = json.loads(payload)
                    code = data.get("status") if isinstance(data, dict) else None
                except (ValueError, UnicodeError):
                    pass
        diagnostic["api_status"] = str(code) if re.fullmatch(r"\d{3}", str(code or "")) else None
        diagnostic["cause"] = "api_error" if diagnostic["api_status"] else "invalid_zip_xml"
        return result()

    codes = {}
    for item in root.findall("list"):
        corp = (item.findtext("corp_code") or "").strip()
        stock = (item.findtext("stock_code") or "").strip()
        if corp and stock:
            codes[stock] = corp
    diagnostic.update(stage="mapping", cause="ok" if codes else "empty_mapping", mapped_count=len(codes))
    return result(codes)
