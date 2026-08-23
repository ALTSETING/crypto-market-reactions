from __future__ import annotations
import numpy as np
import pandas as pd
from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.metrics.pairwise import cosine_similarity

def match_primary_to_media(primary:pd.DataFrame,media:pd.DataFrame,threshold=.35,max_days=7):
    """Title/text/time matcher; price reactions are intentionally absent."""
    if primary.empty:return pd.DataFrame(columns=["event_key","primary_id","similarity"])
    corpus=pd.concat([primary.title.fillna(""),media.title.fillna("")],ignore_index=True);matrix=TfidfVectorizer(stop_words="english",ngram_range=(1,2)).fit_transform(corpus)
    scores=cosine_similarity(matrix[:len(primary)],matrix[len(primary):]);rows=[]
    for j,m in media.reset_index(drop=True).iterrows():
        time_ok=(primary.published_at-pd.Timestamp(m.published_at)).abs()<=pd.Timedelta(days=max_days);valid=np.where(time_ok.to_numpy(),scores[:,j],-1);i=int(np.argmax(valid))
        if valid[i]>=threshold:rows.append({"event_key":m.event_key,"primary_id":int(primary.iloc[i].id),"similarity":float(valid[i])})
    return pd.DataFrame(rows)
