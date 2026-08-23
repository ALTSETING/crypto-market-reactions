from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert
from high_impact_sources.models import high_impact_events,high_impact_event_assets

def persist_events(session,events):
    if not events:return {"inserted":0,"duplicates":0,"assets_inserted":0}
    url_hash=dict(session.execute(select(high_impact_events.c.url,high_impact_events.c.content_hash).where(high_impact_events.c.url.in_([e.url for e in events]))).all());urls=set(url_hash)
    hashes=set(session.execute(select(high_impact_events.c.content_hash).where(high_impact_events.c.content_hash.in_([e.content_hash for e in events]))).scalars())
    canonical_values=[e.canonical_url for e in events if e.canonical_url]
    canon=set(session.execute(select(high_impact_events.c.canonical_url).where(high_impact_events.c.canonical_url.in_(canonical_values))).scalars()) if canonical_values else set()
    candidates=[e for e in events if (e.url in urls and url_hash[e.url]!=e.content_hash) or (e.url not in urls and e.content_hash not in hashes and (not e.canonical_url or e.canonical_url not in canon))]
    fresh=[e for e in candidates if e.url not in urls]
    rows=[]
    for e in candidates:
        rows.append({"source":e.source,"source_type":e.source_type,"platform":e.platform,"author_name":e.author_name,"author_handle":e.author_handle,"external_id":e.external_id,"url":e.url,"canonical_url":e.canonical_url,"title":e.title,"body":e.body,"published_at":e.published_at,"modified_at":e.modified_at,"discovered_at":e.discovered_at,"deleted_at":e.deleted_at,"time_source":e.time_source,"time_confidence":e.time_confidence,"source_authenticity":e.source_authenticity,"crypto_relevance":e.crypto_relevance,"content_hash":e.content_hash,"event_group_id":e.raw_metadata_json.get("event_group_id"),"raw_metadata_json":e.raw_metadata_json,"status":e.raw_metadata_json.get("status","accepted"),"rejection_reason":e.raw_metadata_json.get("rejection_reason")})
    if rows:
        statement=insert(high_impact_events).values(rows)
        mutable={key:statement.excluded[key] for key in rows[0] if key not in ("url","created_at")}
        session.execute(statement.on_conflict_do_update(index_elements=["url"],set_=mutable))
    session.flush()
    by_url=dict(session.execute(select(high_impact_events.c.url,high_impact_events.c.id).where(high_impact_events.c.url.in_([e.url for e in candidates]))).all())
    assets=[]
    for event in candidates:
        event_id=by_url.get(event.url)
        if event_id:
            assets += [{"event_id":event_id,"asset":asset,"relevance":event.crypto_relevance,"detection_source":"local_regex_v1"} for asset in event.assets]
    inserted_assets=0
    if assets:
        result=session.execute(insert(high_impact_event_assets).values(assets).on_conflict_do_nothing(index_elements=["event_id","asset"]));inserted_assets=result.rowcount
    return {"inserted":len(fresh),"updated":len(candidates)-len(fresh),"duplicates":len(events)-len(candidates),"assets_inserted":inserted_assets}
