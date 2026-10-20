"""Mandatory dated editorial-package checks, independent of delivery."""
from datetime import date, timedelta
import re


def validate_editorial_quality(release):
    if not re.fullmatch(r"\d{4}-\d{2}-\d{2}_(0900|1300|1700)_editorial", release.get("release", "")):
        return
    day = date.fromisoformat(release["date"])
    errors, identities, primary_urls = [], set(), set()
    counts = {"ru": 0, "kz": 0, "other": 0}
    for i, item in enumerate(release["items"], 1):
        prefix = f"items[{i}]"
        jurisdictions = str(item.get("jurisdictions", "")).casefold()
        group = "ru" if "росси" in jurisdictions else "kz" if "казахстан" in jurisdictions else "other"
        counts[group] += 1
        if item.get("source_published_at"):
            try:
                published = date.fromisoformat(item["source_published_at"])
                if not day - timedelta(days=7) <= published <= day:
                    errors.append(f"{prefix}: публикация вне окна свежести 7 дней")
            except (TypeError, ValueError):
                errors.append(f"{prefix}: нет достоверной source_published_at")
        publication = item.get("publication_date_evidence")
        urls = [source["url"] for source in item.get("sources", [])]
        if publication:
            if publication.get("url") not in urls or len(str(publication.get("source_quote", ""))) < 8:
                errors.append(f"{prefix}: нет цитаты-доказательства даты на указанном первоисточнике")
        review = item.get("editorial_review")
        if review:
            if not review.get("reviewed_by") or len(str(review.get("cross_border_relevance", ""))) < 40:
                errors.append(f"{prefix}: нет редакционной проверки трансграничной релевантности")
            event = str(review.get("event_key", "")).strip().casefold()
            if not event or event in identities:
                errors.append(f"{prefix}: отсутствует или повторяется event_key")
            identities.add(event)
        primary = urls[0] if urls else ""
        if primary in primary_urls:
            errors.append(f"{prefix}: повтор первичного URL")
        primary_urls.add(primary)
        if len(str(item.get("theme", ""))) < 8:
            errors.append(f"{prefix}: нет осмысленной темы")
    if not (1 <= counts['ru'] <= 3 and 1 <= counts['kz'] <= 2 and 5 <= counts['other'] <= 8):
        errors.append(f"география должна быть РФ 1–3, Казахстан 1–2, остальные 5–8; сейчас {counts}")
    if errors:
        raise ValueError("Редакционное качество не подтверждено:\n- " + "\n- ".join(errors))
