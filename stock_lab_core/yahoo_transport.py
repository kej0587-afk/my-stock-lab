"""Keep yfinance TLS verification working in Windows Unicode install paths."""

from functools import lru_cache
import os
from pathlib import Path
import shutil
import tempfile
import threading


_SESSION_LOCK = threading.Lock()


def _is_windows():
    return os.name == "nt"


def _ascii_ca_bundle(source):
    source = Path(source)
    if str(source).isascii():
        return str(source), None
    root = tempfile.gettempdir()
    if not str(root).isascii():
        raise OSError("An ASCII temporary path is required for the curl CA bundle")
    directory = tempfile.TemporaryDirectory(prefix="stock_lab_ca_", dir=root)
    destination = Path(directory.name) / "cacert.pem"
    try:
        shutil.copyfile(source, destination)
    except Exception:
        directory.cleanup()
        raise
    return str(destination), directory


@lru_cache(maxsize=1)
def _windows_yahoo_session():
    import certifi
    from curl_cffi import requests

    source = os.environ.get("REQUESTS_CA_BUNDLE") or os.environ.get("CURL_CA_BUNDLE") or certifi.where()
    if str(source).isascii() and not (
        os.environ.get("REQUESTS_CA_BUNDLE") or os.environ.get("CURL_CA_BUNDLE")
    ):
        return None
    bundle, directory = _ascii_ca_bundle(source)
    session = requests.Session(impersonate="chrome", verify=bundle)
    # In-flight requests must keep their bundle alive even if the cache is cleared.
    session._stock_lab_ca_directory = directory
    return session


def yahoo_session_kwargs():
    """Supply a supported custom session only where the default CA path fails."""
    if not _is_windows():
        return {}
    with _SESSION_LOCK:
        session = _windows_yahoo_session()
    return {"session": session} if session is not None else {}
