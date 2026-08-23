import numpy as np
def reaction_class(pre,post,threshold):
    before=abs(pre)>=threshold;after=abs(post)>=threshold
    return "reacted_both" if before and after else "reacted_before_article" if before else "reacted_after_article" if after else "no_clear_reaction"
def is_late(pre,post,threshold):return bool(abs(pre)>=threshold and abs(pre)>abs(post))
