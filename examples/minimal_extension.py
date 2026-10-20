from podium_dashboard.state import require_owner

ACTIONS = {"hello"}


def hello(p, args):
    """Greet the active milestone's owner."""
    milestone = p.milestone(args[0] if args else None)
    print(f"hello {p.me}: {milestone['id']} {milestone.get('title', '')} is owned by {milestone.get('owner', 'nobody')}")


def note(p, args):
    """note <milestone> <text> [--force]: write a note on a milestone you own."""
    force = "--force" in args
    args = [a for a in args if a != "--force"]
    if len(args) < 2:
        raise SystemExit("note <milestone> <text> [--force]")
    milestone = p.milestone(args[0])
    require_owner(p, milestone["id"], force)
    milestone["note"] = " ".join(args[1:])
    p.save()
    p.event("note", milestone["id"], text=milestone["note"])


def prompt(p, kind, target_id):
    if kind == "plan":
        return f"Plan milestone {target_id}, then run `podium set milestone:{target_id} phase=spec`."
    if kind in ("assign", "handoff"):
        milestone, story = target_id.split("/")
        found = p.story(story, milestone)[1]
        return f"Build story {target_id}: {found.get('title', '')}. Log progress with `podium log {target_id} STARTED <note>`."
    return None


COMMANDS = {"hello": hello, "note": note}
