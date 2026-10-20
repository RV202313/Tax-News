import copy
from datetime import datetime, timezone
import sys
from pathlib import Path
import unittest
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
from editorial_quality import validate_editorial_quality
from publish_batch import _page_text, _source_verifications
from source_http import source_headers

class QualityGate(unittest.TestCase):
    def package(self):
        items = []
        for i in range(10):
            url = f"https://example.test/news/{i}"
            items.append({"jurisdictions": "Россия" if i == 0 else "Казахстан" if i < 3 else "Нидерланды",
                          "source_published_at": "2026-10-02", "sources": [{"url": url}],
                          "theme": "Таможенные процедуры", "publication_date_evidence": {"url": url, "source_quote": "2 October 2026"},
                          "editorial_review": {"reviewed_by": "fixture", "event_key": str(i),
                                               "cross_border_relevance": "Условия применения пошлин и льгот при трансграничных поставках."}})
        return {"date": "2026-10-06", "release": "2026-10-06_0900_editorial", "items": items}
    def test_compliant_geography_dates_and_unique_events(self):
        validate_editorial_quality(self.package())
    def test_stale_missing_dates_quota_and_duplicate_events_fail(self):
        for change in [lambda p: p['items'][0].update(source_published_at='2026-09-15'),
                       lambda p: p['items'][0].pop('publication_date_evidence'),
                       lambda p: p['items'][0].update(jurisdictions='Нидерланды'),
                       lambda p: p['items'][4]['editorial_review'].update(event_key='3')]:
            p=self.package();change(p)
            with self.assertRaises(ValueError):validate_editorial_quality(p)
    def test_script_metadata_is_not_visible_evidence(self):
        self.assertNotIn('invented tax facts', _page_text(b'<html><script>invented tax facts</script><p>visible</p></html>', 'text/html'))
    def test_attested_redirect_cannot_approve_different_source(self):
        item={'sources':[{'url':'https://example.test/news'}], 'source_verifications':[{'url':'https://example.test/news', 'final_url':'https://example.test/sports', 'status_code':200, 'checked_at':datetime.now(timezone.utc).isoformat(), 'evidence':[{'claim':'Русское утверждение новости.', 'source_quote':'Actual official tax news evidence'}]}]}
        with self.assertRaisesRegex(ValueError,'final_url'):_source_verifications(item)
    def test_gov_rss_and_visible_article_use_correct_public_renditions(self):
        self.assertEqual(source_headers('https://www.gov.kz/memleket/entities/kgd/press/news/1')['User-Agent'],'curl/8.0')
        self.assertNotEqual(source_headers('https://www.gov.kz/api/v1/public/rss/kgd/news/ru')['User-Agent'],'curl/8.0')
        self.assertNotEqual(source_headers('https://gov.kz.evil.test/news')['User-Agent'],'curl/8.0')

if __name__ == '__main__': unittest.main()
