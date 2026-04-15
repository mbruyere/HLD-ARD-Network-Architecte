"""Narrow SR Linux `set /` CLI → gNMI (path, value) translator.

Scope: the three template chains we actually render in Slice 2–5
(`srl_base.j2`, `srl_interfaces.j2`, `srl_vlans.j2`). Each pattern
below corresponds to exactly one line shape those templates emit,
verified live against `ghcr.io/nokia/srlinux:latest` (gNMI v0.10.0).

Returning `None` from `parse_line` means "ignore" — blank lines and
comments. Unrecognised non-empty lines raise `UnknownCliLine` so a
template change doesn't silently drop config.
"""
from __future__ import annotations

import re
import shlex
from typing import Any, List, Optional, Tuple


class UnknownCliLine(ValueError):
    pass


GnmiUpdate = Tuple[str, dict]


def _strip_prefix(line: str) -> Optional[str]:
    s = line.strip()
    if not s or s.startswith("#"):
        return None
    if s.startswith("set / "):
        return s[len("set / "):]
    if s.startswith("set /"):
        return s[len("set /"):]
    raise UnknownCliLine(line)


def _tokens(body: str) -> List[str]:
    # shlex handles the quoted `description "..."` case cleanly.
    return shlex.split(body)


def parse_line(line: str) -> Optional[GnmiUpdate]:
    body = _strip_prefix(line)
    if body is None:
        return None
    tok = _tokens(body)

    # /system/name/host-name <val>
    if tok[:3] == ["system", "name", "host-name"] and len(tok) == 4:
        return ("/system/name", {"host-name": tok[3]})

    # /system/information/location "<val>"
    if tok[:3] == ["system", "information", "location"] and len(tok) == 4:
        return ("/system/information", {"location": tok[3]})

    # /interface <name> ...
    if tok[0] == "interface" and len(tok) >= 3:
        ifname = tok[1]
        rest = tok[2:]
        ifpath = f"/interface[name={ifname}]"

        # interface X admin-state <state>
        if rest[:1] == ["admin-state"] and len(rest) == 2:
            return (ifpath, {"admin-state": rest[1]})
        # interface X description "<val>"
        if rest[:1] == ["description"] and len(rest) == 2:
            return (ifpath, {"description": rest[1]})
        # interface X vlan-tagging <bool>
        if rest[:1] == ["vlan-tagging"] and len(rest) == 2:
            return (ifpath, {"vlan-tagging": rest[1].lower() == "true"})

        # interface X subinterface <idx> ...
        if rest[:1] == ["subinterface"] and len(rest) >= 3:
            idx = rest[1]
            sub = rest[2:]
            subpath = f"{ifpath}/subinterface[index={idx}]"

            if sub[:1] == ["type"] and len(sub) == 2:
                return (subpath, {"type": sub[1]})
            if sub[:1] == ["description"] and len(sub) == 2:
                return (subpath, {"description": sub[1]})
            # subinterface <idx> vlan encap single-tagged vlan-id <N>
            if sub[:4] == ["vlan", "encap", "single-tagged", "vlan-id"] and len(sub) == 5:
                return (
                    f"{subpath}/vlan/encap/single-tagged",
                    {"vlan-id": int(sub[4])},
                )

    # /network-instance <name> ...
    if tok[0] == "network-instance" and len(tok) >= 3:
        ni = tok[1]
        rest = tok[2:]
        nipath = f"/network-instance[name={ni}]"

        if rest[:1] == ["type"] and len(rest) == 2:
            return (nipath, {"type": rest[1]})
        # network-instance X interface <ref>
        if rest[:1] == ["interface"] and len(rest) == 2:
            return (f"{nipath}/interface[name={rest[1]}]", {})

    raise UnknownCliLine(line)


def cli_to_gnmi_updates(content: str) -> List[GnmiUpdate]:
    """Translate a rendered SR Linux `set /` config blob to gNMI updates.

    Later lines under the same path are merged — gNMI treats multiple
    leaves on one container as a single JSON object, which is both
    faster (one Set op) and semantically what the CLI set-set-set chain
    means.
    """
    merged: dict[str, dict] = {}
    order: List[str] = []
    for line in content.splitlines():
        try:
            result = parse_line(line)
        except UnknownCliLine:
            raise
        if result is None:
            continue
        path, value = result
        if path not in merged:
            merged[path] = {}
            order.append(path)
        # Empty-value list entries (e.g. network-instance interface refs)
        # still need to register their path but contribute no leaves.
        merged[path].update(value)
    return [(p, merged[p]) for p in order]
