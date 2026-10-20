"""Shared HTTP setup for reliable TLS and transient-error retries."""

import os

import truststore

if os.name == "nt":
    truststore.inject_into_ssl()

from requests import Session
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry


def new_session() -> Session:
    retry = Retry(
        total=2,
        connect=2,
        read=2,
        status=2,
        backoff_factor=1,
        status_forcelist=(429, 500, 502, 503, 504),
        allowed_methods=frozenset({"GET", "HEAD"}),
        respect_retry_after_header=True,
    )
    session = Session()
    adapter = HTTPAdapter(max_retries=retry)
    session.mount("http://", adapter)
    session.mount("https://", adapter)
    return session
