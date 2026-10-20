"""The three-way merge of podium.json: concurrent commands' writes, and two machines' saves."""


def rebase(base, mine, theirs):
    """`theirs`, podium.json as other commands left it, with this command's changes since it read `base` on top:
    values it set, keys it added or removed, list items it changed, added or removed. List items with an `id`
    (epics, milestones, stories) pair up by id, others by position. An object both added merges key by key. Where both
    changed one value, this command's wins."""
    if mine == base:
        return theirs
    if theirs == base:
        return mine
    if isinstance(base, dict) and isinstance(mine, dict) and isinstance(theirs, dict):
        out = dict(theirs)
        for k in list(base) + [k for k in mine if k not in base]:
            if k not in mine:
                out.pop(k, None)
            elif k in base and k in theirs:
                out[k] = rebase(base[k], mine[k], theirs[k])
            elif k in theirs and isinstance(mine[k], dict) and isinstance(theirs[k], dict):
                out[k] = rebase({}, mine[k], theirs[k])
            elif k not in base or mine[k] != base[k]:  # added here, or changed here and removed there
                out[k] = mine[k]
        return out
    if isinstance(base, list) and isinstance(mine, list) and isinstance(theirs, list):
        ids = lambda xs: [x.get("id") if isinstance(x, dict) else None for x in xs]
        if None not in ids(base) + ids(mine) + ids(theirs):
            b, m, t_ids = dict(zip(ids(base), base)), dict(zip(ids(mine), mine)), ids(theirs)
            out = [rebase(b[t["id"]], m[t["id"]], t) if t["id"] in b and t["id"] in m else t
                   for t in theirs if t["id"] in m or t["id"] not in b]
            return out + [x for x in mine if x["id"] not in b and x["id"] not in t_ids]
        if len(mine) >= len(base) <= len(theirs):
            n = len(base)
            return [rebase(*x) for x in zip(base, mine, theirs)] + theirs[n:] + mine[n:]
    return mine
