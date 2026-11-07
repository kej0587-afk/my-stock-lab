"""Collect once per report; reuse only a freshly checked public issuer packet."""

from copy import deepcopy
import threading
import time

from lxml import etree
import requests

from stock_lab_core.msft_ir_source import load_msft_business_evidence
from stock_lab_core.report_msft import usable_packet
from stock_lab_core.report_build import register_loaded_source

register_loaded_source(__name__, __file__)

_LOCK = threading.Lock()
_CACHE = {}
SUCCESS_TTL = 6 * 3600


def collect_msft_report_evidence(now, *, loader=None):
    # Only public IR data shared across sessions. No account state or decisions.
    with _LOCK:
        packet = _CACHE.get('packet')
        if loader is None and time.monotonic() - _CACHE.get('at', 0) < SUCCESS_TTL and usable_packet(packet, now):
            return dict(packet=deepcopy(packet), collection='success_cache')
        try:
            packet = (loader or load_msft_business_evidence)(now)
            if not usable_packet(packet, now):
                raise ValueError('unverified_packet')
        except (requests.RequestException, ValueError, TypeError, KeyError, etree.LxmlError):
            # Do not silently substitute a stale success or cache failed results.
            return dict(packet=None, collection='unavailable', reason='official_source_unavailable_or_unverified')
        if loader is None and packet.get('status') == 'confirmed':
            _CACHE.update(packet=deepcopy(packet), at=time.monotonic())
        return dict(packet=packet, collection='collected')
