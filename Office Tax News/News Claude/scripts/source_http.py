"""Public-source request headers shared by collection and live verification."""
from urllib.parse import urlsplit

DEFAULT_UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/128.0.0.0 Safari/537.36"


def source_headers(url):
    host = (urlsplit(url).hostname or "").lower()
    # GOV.KZ serves its public, readable rendition to curl-compatible clients.
    # Browser requests receive only a JavaScript application shell. The URL,
    # public content and TLS verification remain identical.
    public_page = (host == "gov.kz" or host.endswith(".gov.kz")) and not urlsplit(url).path.startswith("/api/")
    agent = "curl/8.0" if public_page else DEFAULT_UA
    return {"User-Agent": agent, "Accept": "text/html,application/xhtml+xml,text/plain;q=0.9,*/*;q=0.8"}
