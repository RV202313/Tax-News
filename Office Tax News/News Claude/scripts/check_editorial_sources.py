#!/usr/bin/env python3
"""Checkpoint visible source evidence. Never approve or deliver."""
from __future__ import annotations
import argparse
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone
from html.parser import HTMLParser
import json
import os
from pathlib import Path
import ssl
import sys
import tempfile
import time
from urllib.parse import urlsplit
from urllib.request import Request, urlopen
from source_http import source_headers

MAX_BYTES = 2_000_000

def normalize(value):
    return " ".join(str(value or "").split())

class VisibleText(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.parts = []
        self.suppressed = []
    def handle_starttag(self, tag, attrs):
        if tag in {"script", "style", "noscript", "template"} or "hidden" in dict(attrs):
            self.suppressed.append(tag)
        elif self.suppressed:
            self.suppressed.append(tag)
    def handle_endtag(self, tag):
        if tag in self.suppressed:
            index = len(self.suppressed) - 1 - self.suppressed[::-1].index(tag)
            del self.suppressed[index:]
    def handle_data(self, value):
        if not self.suppressed:
            self.parts.append(value)

def page_text(content, content_type):
    media = content_type.split(";", 1)[0].lower().strip()
    if media not in {"text/html", "application/xhtml+xml", "text/plain"}:
        raise ValueError(f"unreadable source Content-Type: {media}")
    charset = "utf-8"
    for part in content_type.split(";")[1:]:
        if part.strip().lower().startswith("charset="):
            charset = part.split("=", 1)[1].strip().strip('"')
    decoded = content.decode(charset, errors="strict")
    if media == "text/plain":
        return normalize(decoded)
    parser = VisibleText()
    parser.feed(decoded)
    return normalize(" ".join(parser.parts))

def atomic_json(path, value):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temporary = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            json.dump(value, handle, ensure_ascii=False, indent=2)
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
        for attempt in range(6):
            try:
                os.replace(temporary, path)
                break
            except PermissionError:
                if attempt == 5:
                    raise
                time.sleep(0.1 * 2 ** attempt)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)

def ssl_context():
    context = ssl.create_default_context()
    try:
        import certifi
    except ImportError:
        pass
    else:
        context.load_verify_locations(cafile=certifi.where())
    return context

def check_candidate(item, *, timeout=12, deadline=None, opener=urlopen):
    results = []
    proofs = {entry.get("url"): entry for entry in item.get("source_verifications", [])}
    for source in item.get("sources") or []:
        url = source.get("url", "")
        result = {"url": url, "checked_at": datetime.now(timezone.utc).isoformat(),
                  "performed": False, "passed": False}
        try:
            if deadline and datetime.now(timezone.utc) >= deadline:
                raise ValueError("preparation_deadline_elapsed")
            parts = urlsplit(url)
            if parts.scheme not in {"http", "https"} or not parts.netloc:
                raise ValueError("invalid source URL")
            evidence = proofs.get(url, {}).get("evidence")
            if not isinstance(evidence, list) or not evidence:
                raise ValueError("missing evidence")
            caption = normalize(item.get("caption"))
            if url not in caption:
                raise ValueError("source URL missing from caption")
            for proof in evidence:
                if len(normalize(proof.get("claim"))) < 12 or len(normalize(proof.get("source_quote"))) < 16:
                    raise ValueError("missing or short claim/source_quote")
                if normalize(proof["claim"]) not in caption:
                    raise ValueError("claim missing from caption")
            remaining = (deadline - datetime.now(timezone.utc)).total_seconds() if deadline else timeout
            if remaining <= 0:
                raise ValueError("preparation_deadline_elapsed")
            result["performed"] = True
            with opener(Request(url, headers=source_headers(url)), timeout=min(timeout, remaining), context=ssl_context()) as response:
                result.update(status_code=response.getcode(), final_url=response.geturl())
                content_type = response.headers.get("Content-Type", "")
                content = response.read(MAX_BYTES + 1)
            if result["status_code"] != 200:
                raise ValueError(f"HTTP {result['status_code']}")
            if result["final_url"] != url:
                raise ValueError("final URL differs from cited source URL")
            if len(content) > MAX_BYTES:
                raise ValueError("source response exceeds 2 MB")
            visible = page_text(content, content_type)
            if not all(normalize(proof["source_quote"]) in visible for proof in evidence):
                raise ValueError("quote absent from visible source text")
            result.update(passed=True, evidence=evidence)
        except Exception as exc:
            result["error"] = f"{type(exc).__name__}: {exc}"
        results.append(result)
    return {"passed": bool(results) and all(result["passed"] for result in results), "checks": results}

def checkpoint_candidates(data, output, *, workers=6, timeout=12, deadline=None, checker=check_candidate, report=print):
    items = data.get("candidates")
    if not isinstance(items, list) or not items:
        raise ValueError("expected nonempty candidates list (not an approved package)")
    data.update(approved=False, source_gate_candidate_count=0, current_run_completed_count=0)
    for item in items:
        if item.get("current_run_check"):
            item["previous_run_check"] = item["current_run_check"]
        item["current_run_check"] = {"passed": False, "pending": True}
    atomic_json(output, data)
    with ThreadPoolExecutor(max_workers=workers) as executor:
        futures = {executor.submit(checker, item, timeout=timeout, deadline=deadline): index for index, item in enumerate(items)}
        for future in as_completed(futures):
            index = futures[future]
            try:
                result = future.result()
            except Exception as exc:
                result = {"passed": False, "error": f"{type(exc).__name__}: {exc}", "checks": []}
            item = items[index]
            item["current_run_check"] = result
            item["source_gate_passed"] = result["passed"]
            if result["passed"]:
                item["source_verifications"] = [{key: check[key] for key in ("url", "checked_at", "status_code", "final_url", "evidence")} for check in result["checks"]]
            data["current_run_completed_count"] += 1
            data["source_gate_candidate_count"] += int(result["passed"])
            data["checked_at"] = datetime.now(timezone.utc).isoformat()
            atomic_json(output, data)
            try:
                report(json.dumps({"candidate": index + 1, "passed": result["passed"]}, ensure_ascii=True))
            except (UnicodeError, OSError):
                pass
    return data

def main():
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(encoding="utf-8", errors="backslashreplace")
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("candidates", type=Path)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--deadline", required=True)
    parser.add_argument("--workers", type=int, choices=range(1, 13), default=6)
    parser.add_argument("--timeout", type=int, choices=range(1, 31), default=12)
    args = parser.parse_args()
    try:
        if "approved" in {part.lower() for part in args.output.resolve().parts}:
            raise ValueError("checkpoint output must not be in approved directory")
        deadline = datetime.fromisoformat(args.deadline)
        if deadline.tzinfo is None:
            raise ValueError("deadline must include timezone")
        data = json.loads(args.candidates.read_text(encoding="utf-8-sig"))
        result = checkpoint_candidates(data, args.output, workers=args.workers, timeout=args.timeout, deadline=deadline)
        print(json.dumps({"source_gate_candidate_count": result["source_gate_candidate_count"], "editorial_approved": False}, ensure_ascii=True))
        return 0 if result["source_gate_candidate_count"] == len(result["candidates"]) else 1
    except (OSError, ValueError) as exc:
        print(str(exc), file=sys.stderr)
        return 1

if __name__ == "__main__":
    raise SystemExit(main())
