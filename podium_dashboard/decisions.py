"""Epic decisions: questions touching two or more milestones of an epic, settled before its milestone cut. `decision`
changes one, `decisions` lists them with the frontier and the epic's state."""
import json
import re
import sys

from podium_dashboard import sync
from podium_dashboard.commands import refuse, split_flags, take
from podium_dashboard.state import NOW

TYPES = ("discussion", "research", "prototype", "unblock")
CLOSED = {"resolve": ("resolved", "RESOLVED"), "outscope": ("out-of-scope", "OUT-OF-SCOPE"),
          "invalidate": ("invalidated", "INVALIDATED")}
CAP = 6
ADD_USAGE = 'decision add "<question>" --type <discussion|research|prototype|unblock> [--epic <id>] [--affects "a,b"] [--blocked-by D1,D2] [--force]'
USAGE = "\n".join(["decision <verb> ...", f"  {ADD_USAGE}", "  decision claim <D<n>> [--force]",
                   '  decision resolve|outscope|invalidate <D<n>> "<outcome or why>" [--force]',
                   '  decision unresolved <D<n>> "<missing>" [--force]'])


def records(p):
    found = p.data.get("decisions")
    return [d for d in found if isinstance(d, dict) and isinstance(d.get("id"), str)] if isinstance(found, list) else []


def decision(p, decision_id):
    found = next((d for d in records(p) if d.get("id") == decision_id), None)
    if not found:
        sys.exit(f"no decision {decision_id!r}")
    return found


def open_decision(p, decision_id):
    d = decision(p, decision_id)
    if d.get("status") != "open":
        sys.exit(f"podium: decision {decision_id} is {d.get('status')}")
    return d


def listed(value):
    return [x.strip() for x in (value or "").split(",") if x.strip()]


def next_id(p):
    numbers = [int(m[1]) for d in records(p) for m in [re.fullmatch(r"D(\d+)", d["id"])] if m]
    return f"D{max(numbers, default=0) + 1}"


def add(p, args):
    force, args = "--force" in args, [a for a in args if a != "--force"]
    values, rest = split_flags(args, ("--type", "--epic", "--affects", "--blocked-by"), ADD_USAGE)
    if len(rest) != 1 or not rest[0].strip() or values.get("--type") not in TYPES:
        sys.exit(ADD_USAGE)
    if p.synced():
        sync.pull(p)
    epic = values.get("--epic") or p.active().get("epic")
    if not epic:
        sys.exit("podium: which epic? pass --epic <id>")
    epic = p.resolve(f"epic:{epic}")[0]["id"]
    with p.locked():
        p.refresh()
        blocked_by = listed(values.get("--blocked-by"))
        for b in blocked_by:
            decision(p, b)
        if not force and sum(d.get("epic") == epic and d.get("status") == "open" for d in records(p)) >= CAP:
            sys.exit(f"CAP {CAP} open decisions on {epic}: resolve, rule out or fold one first")
        did = next_id(p)
        d = {"id": did, "epic": epic, "question": rest[0], "type": values["--type"], "affects": listed(values.get("--affects")),
             "blockedBy": blocked_by, "status": "open", "at": NOW()}
        if not isinstance(p.data.get("decisions"), list):
            p.data["decisions"] = []
        p.data["decisions"].append(d)
        p.save()
    p.event("decision", decision=did, epic=epic, kind=d["type"], question=d["question"])
    print(f"DECISION {did} open")


def claim(p, args):
    force, rest = "--force" in args, [a for a in args if a != "--force"]
    if len(rest) != 1:
        sys.exit("decision claim <D<n>> [--force]")
    did, owner = take(p, rest[0], lambda decision_id: open_decision(p, decision_id), "decision", force)
    if owner != p.me:
        p.event("decision-claimed", decision=did, owner=p.me, **({"from": owner} if owner else {}))
    print(f"CLAIMED {did}")


def owned(p, d, force):
    """Exit 1 while someone else holds decision `d`, unless `force`; an unclaimed decision is anyone's to change."""
    if d.get("owner") and d["owner"] != p.me and not force:
        refuse(d["id"], d["owner"], "decision")
    return d


def close(p, verb, args):
    force, args = "--force" in args, [a for a in args if a != "--force"]
    if len(args) != 2 or not args[1].strip():
        sys.exit(f'decision {verb} <D<n>> "<{"outcome" if verb == "resolve" else "why"}>" [--force]')
    status, label = CLOSED[verb]
    d = owned(p, decision(p, args[0]), force)
    d["status"], d["outcome"] = status, args[1]
    d.pop("missing", None)
    p.save()
    p.event("decision-closed", decision=d["id"], status=status, outcome=args[1])
    print(f"{label} {d['id']}")


def unresolved(p, args):
    force, args = "--force" in args, [a for a in args if a != "--force"]
    if len(args) != 2 or not args[1].strip():
        sys.exit('decision unresolved <D<n>> "<missing>" [--force]')
    d = owned(p, open_decision(p, args[0]), force)
    d["missing"] = args[1]
    p.save()
    p.event("decision-unresolved", decision=d["id"], missing=args[1])
    print(f"OPEN {d['id']} missing: {args[1]}")


def cmd_decision(p, args):
    verb, rest = (args[0], args[1:]) if args else (None, [])
    if verb == "add":
        add(p, rest)
    elif verb == "claim":
        claim(p, rest)
    elif verb in CLOSED:
        close(p, verb, rest)
    elif verb == "unresolved":
        unresolved(p, rest)
    else:
        sys.exit(USAGE)


def open_blockers(d, by_id):
    blocked_by = d.get("blockedBy") if isinstance(d.get("blockedBy"), list) else []
    return [b for b in blocked_by if isinstance(b, str) and (by_id.get(b) or {}).get("status") == "open"]


def frontier(shown, by_id):
    """The open decisions nobody has claimed whose blockers are all closed."""
    return [d["id"] for d in shown if d.get("status") == "open" and not d.get("owner") and not open_blockers(d, by_id)]


def state(shown, by_id):
    open_ = [d for d in shown if d.get("status") == "open"]
    if frontier(shown, by_id):
        return "ACTIVE"
    if any(d.get("owner") for d in open_):
        return "WAITING"
    return "BLOCKED" if open_ else "CLEAR"


def cmd_decisions(p, args):
    usage = "decisions [--epic <id>] [--json]"
    as_json, args = "--json" in args, [a for a in args if a != "--json"]
    values, rest = split_flags(args, ("--epic",), usage)
    if rest:
        sys.exit(usage)
    epic = values.get("--epic") and p.resolve(f"epic:{values['--epic']}")[0]["id"]
    every = records(p)
    by_id = {d["id"]: d for d in every}
    shown = [d for d in every if not epic or d.get("epic") == epic]
    front, now = frontier(shown, by_id), state(shown, by_id)
    if as_json:
        print(json.dumps({"decisions": shown, "frontier": front, "state": now}, ensure_ascii=False))
        return
    for d in shown:
        print(f"DECISION {d.get('id')} {d.get('status')} {d.get('type')} {d.get('owner') or '-'}"
              f" blocked={','.join(open_blockers(d, by_id)) or '-'} — {d.get('question')}")
    print(f"FRONTIER {','.join(front) or 'none'}")
    print(f"STATE {now}")
