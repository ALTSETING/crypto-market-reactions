from datetime import date
from xml.etree import ElementTree
from high_impact_sources.parsers.content_cleaner import clean_content
from high_impact_sources.parsers.timestamp_parser import parse_timestamp
from high_impact_sources.schemas import HighImpactEvent
from .base_source import BaseSource

class SECSource(BaseSource):
    name="sec";source_type="regulator";platform="sec";min_interval=.11
    feeds={
      "press_release":"https://www.sec.gov/news/pressreleases.rss",
      "speech_statement":"https://www.sec.gov/news/speeches-statements.rss",
      "litigation_release":"https://www.sec.gov/litigation/litreleases.rss",
    }
    edgar_issuers={
      "1679788":("Coinbase Global","cryptocurrency exchange and digital assets"),
      "1050446":("Strategy","bitcoin digital asset treasury"),
      "1852317":("iShares Bitcoin Trust ETF","bitcoin crypto ETF"),
      "1588489":("Grayscale Bitcoin Trust","bitcoin crypto ETF"),
      "1725210":("Grayscale Ethereum Trust","ethereum ether crypto ETF"),
    }
    def fetch(self,start: date|None=None,end: date|None=None,limit: int|None=None):
        events=[];errors=[]
        for kind,url in self.feeds.items():
            try: root=ElementTree.fromstring(self.get(url).content)
            except Exception as exc: errors.append({"feed":kind,"error":str(exc)});continue
            for item in root.findall(".//item"):
                title=clean_content(item.findtext("title") or ""); link=(item.findtext("link") or "").strip(); body=clean_content(item.findtext("description") or ""); raw=item.findtext("pubDate")
                if not title or not link or not raw:continue
                published=parse_timestamp(raw)
                if start and published.date()<start:continue
                if end and published.date()>end:continue
                events.append(HighImpactEvent(source=self.name,source_type=self.source_type,platform=self.platform,url=link,canonical_url=link,external_id=(item.findtext("guid") or link).strip(),title=title,body=body or title,published_at=published,time_source="official_rss_pubdate",time_confidence=.95,raw_metadata_json={"document_kind":kind,"feed":url}))
        forms={"8-K","10-K","10-Q","S-1","S-3","424B3","DEF 14A","8-A12B"}
        for cik,(company,descriptor) in self.edgar_issuers.items():
            try:data=self.get(f"https://data.sec.gov/submissions/CIK{int(cik):010d}.json",api=True).json();recent=data["filings"]["recent"]
            except Exception as exc:errors.append({"feed":f"edgar:{cik}","error":str(exc)});continue
            for index,form in enumerate(recent.get("form",[])):
                if form not in forms:continue
                published=parse_timestamp(recent["filingDate"][index])
                if start and published.date()<start:continue
                if end and published.date()>end:continue
                accession=recent["accessionNumber"][index];primary=recent["primaryDocument"][index]
                link=f"https://www.sec.gov/Archives/edgar/data/{int(cik)}/{accession.replace('-','')}/{primary}"
                body=f"Official EDGAR filing by {company}. Form {form}. Filed {recent['filingDate'][index]}. Accession {accession}. Primary document {primary}."
                events.append(HighImpactEvent(source=self.name,source_type=self.source_type,platform="edgar",url=link,canonical_url=link,external_id=accession,title=f"{company} {form} filing {accession}",body=body,published_at=published,time_source="edgar_filing_date",time_confidence=.60,raw_metadata_json={"document_kind":"edgar_filing_metadata","cik":cik,"company":company,"issuer_scope":descriptor,"form":form,"accession_number":accession,"primary_document":primary,"content_scope":"official_submission_metadata; primary document linked but not scraped"}))
        events.sort(key=lambda x:x.published_at,reverse=True)
        if limit:events=events[:limit]
        for event in events:event.raw_metadata_json["fetch_errors"]=errors
        return events
    def availability(self):
        return {**super().availability(),"channels":"press releases; speeches/statements; litigation releases; scoped EDGAR submissions metadata","edgar":"enabled for configured crypto-native/crypto-trust issuers; primary document linked but not scraped in Phase 1","history_depth":"official RSS retention plus recent submissions arrays, bounded by CLI date/limit","timestamp_precision":"RSS seconds/minutes; EDGAR filing date only (confidence 0.60)","rate_limit":"<=10 requests/second; adapter uses <=9.1/s","restrictions":"official User-Agent required; robots fail-closed; no CAPTCHA/auth bypass"}
