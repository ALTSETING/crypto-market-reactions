def deduplicate(events):
    seen_url=set();seen_canonical=set();seen_hash=set();unique=[];duplicates=[]
    for event in events:
        keys=(event.url,event.canonical_url,event.content_hash)
        if event.url in seen_url or (event.canonical_url and event.canonical_url in seen_canonical) or event.content_hash in seen_hash:duplicates.append(event);continue
        seen_url.add(event.url);seen_hash.add(event.content_hash)
        if event.canonical_url:seen_canonical.add(event.canonical_url)
        unique.append(event)
    return unique,duplicates
