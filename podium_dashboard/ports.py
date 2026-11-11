"""Per-machine port leases: `ports.json` beside human.json, `{slug: {port, used, dir, pinned?}}`, so a run keeps its port,
and with it the page's settings in the browser, from one start to the next.

A run whose leased port is free takes it; one whose port serves the same run already is refused; one whose port
something else holds takes a free port and keeps its lease. A run without a lease takes the first free port of the
range that no live lease holds. A lease is live while `used` is under 7 days old, or while it is pinned; an expired one
counts as free and goes when another run takes its port. The server writes `used` at start and about hourly while it
serves. Every write drops the leases whose dir is gone. The file is only ever replaced whole: the port's bind is the
lock, so there is no file lock.
"""
import json
import os
import socket
import sys
from datetime import datetime, timedelta, timezone

from podium_dashboard import human
from podium_dashboard.files import write_atomic
from podium_dashboard.state import http

LIVE = timedelta(days=7)
REFRESH = 3600
DONE = {"release": "released", "pin": "pinned", "unpin": "unpinned"}


def path():
    return os.path.join(os.path.dirname(human.HUMAN_FILE), "ports.json")


def read():
    """The leases, each with a whole-number port and a dir; anything else in the file is left out."""
    try:
        with open(path()) as f:
            data = json.load(f)
    except (OSError, ValueError):
        return {}
    if not isinstance(data, dict):
        return {}
    return {slug: lease for slug, lease in data.items()
            if isinstance(lease, dict) and type(lease.get("port")) is int and isinstance(lease.get("dir"), str)}


def write(leases):
    os.makedirs(os.path.dirname(path()), exist_ok=True)
    kept = {slug: lease for slug, lease in leases.items() if os.path.isdir(lease["dir"])}
    write_atomic(path(), json.dumps(kept, indent=1, sort_keys=True))


def stamp(now):
    return now.isoformat(timespec="seconds")


def live(lease, now):
    if lease.get("pinned") is True:
        return True
    try:
        return now - datetime.fromisoformat(lease.get("used") or "") < LIVE
    except (TypeError, ValueError):
        return False


def busy(port):
    with socket.socket() as s:
        return s.connect_ex(("127.0.0.1", port)) == 0


def serving(port):
    """The run the Podium on `port` serves, or None."""
    got = http(f"http://127.0.0.1:{port}/info", timeout=0.5)
    return got.get("run") if isinstance(got, dict) else None


def first_free(candidates):
    return next((port for port in candidates if not busy(port)), None)


class Served(Exception):
    def __init__(self, port):
        super().__init__(port)
        self.port = port


def take(slug, root, first, count, explicit=None, now=None):
    """The port run `slug` (at `root`) serves on, its lease written. `explicit`, a --port, takes the first free port from
    it and records that. Raises Served when the leased port serves this run already; exits when no port is free."""
    now = now or datetime.now(timezone.utc)
    leases = read()
    lease = leases.get(slug)
    span = range(explicit, explicit + count) if explicit is not None else range(first, first + count)
    if explicit is not None:
        port = first_free(span)
    elif lease and not busy(lease["port"]):
        port = lease["port"]
    elif lease and serving(lease["port"]) == slug:
        raise Served(lease["port"])
    else:
        held = {other["port"] for name, other in leases.items() if name != slug and live(other, now)}
        port = first_free(p for p in span if p not in held) or first_free(span)
    if port is None:
        sys.exit(f"no free port in {span.start}-{span.stop - 1}")
    kept = lease["port"] if lease and explicit is None else port
    leases = {name: other for name, other in leases.items() if name == slug or other["port"] != port or live(other, now)}
    leases[slug] = {**(lease or {}), "port": kept, "used": stamp(now), "dir": root}
    write(leases)
    return port


def touch(slug, root, port, now=None):
    """Mark run `slug`'s lease used now, while it serves on `port`: its leased port stays, a released lease returns."""
    leases = read()
    lease = leases.get(slug) or {"port": port}
    leases[slug] = {**lease, "used": stamp(now or datetime.now(timezone.utc)), "dir": root}
    write(leases)


def cmd_ports(p, args):
    if len(args) == 2 and args[0] in DONE:
        verb, slug = args
        leases = read()
        if slug not in leases:
            sys.exit(f"ports: no lease for {slug}")
        if verb == "release":
            del leases[slug]
        elif verb == "pin":
            leases[slug]["pinned"] = True
        else:
            leases[slug].pop("pinned", None)
        write(leases)
        print(f"{DONE[verb]} {slug}")
        return
    if args:
        sys.exit("ports [release|pin|unpin <slug>]")
    leases, now = read(), datetime.now(timezone.utc)
    if not leases:
        print(f"no leases ({path()})")
    for slug, lease in sorted(leases.items(), key=lambda item: (item[1]["port"], item[0])):
        state = "live" if serving(lease["port"]) == slug else "stopped"
        flag = "pinned" if lease.get("pinned") is True else "-" if live(lease, now) else "expired"
        print(f"{slug} {lease['port']} {state} {lease.get('used') or '-'} {flag} {lease['dir']}")
