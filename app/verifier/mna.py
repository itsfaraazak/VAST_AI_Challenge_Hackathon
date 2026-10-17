"""Small pure-Python modified nodal analysis for DC breadboard circuits."""
from __future__ import annotations

from typing import Any


def solve_dc(norm: dict) -> dict:
    """Return voltages, currents, and flags. Handles R, ideal V source, PWL LED."""
    comps = {c["id"]: c for c in norm["components"]}
    # Build node mapping from endpoints
    nodes: dict[str, int] = {"gnd": 0}
    def nid(name: str) -> int:
        if name not in nodes:
            nodes[name] = len(nodes)
        return nodes[name]

    # Expand nets into node ids per endpoint
    ep_node: dict[str, int] = {}
    for net in norm["nets"]:
        # pick canonical node name = first endpoint
        root = net[0]
        for e in net:
            ep_node[e] = nid(root)

    # Ensure supply pins
    supplies = [c for c in comps.values() if c["type"] == "supply"]
    resistors = [c for c in comps.values() if c["type"] == "resistor"]
    leds = [c for c in comps.values() if c["type"] == "led"]

    gnd_eps = [e for e in ep_node if e.endswith(".neg") or e.endswith(".k") and e.split(".")[0] in {s["id"] for s in supplies}]
    # Map supply neg to gnd
    for s in supplies:
        neg = f"{s['id']}.neg"
        pos = f"{s['id']}.pos"
        if neg in ep_node:
            # merge node to gnd
            old = ep_node[neg]
            for e, n in list(ep_node.items()):
                if n == old:
                    ep_node[e] = 0
        else:
            ep_node[neg] = 0
        if pos not in ep_node:
            ep_node[pos] = nid(pos)

    n = max(ep_node.values(), default=0) + 1
    # Conductance matrix G[n][n], RHS b[n]
    G = [[0.0] * n for _ in range(n)]
    b = [0.0] * n

    def stamp_resistor(n1: int, n2: int, r: float) -> None:
        if r <= 0:
            r = 1e-6
        g = 1.0 / r
        if n1:
            G[n1][n1] += g
        if n2:
            G[n2][n2] += g
        if n1 and n2:
            G[n1][n2] -= g
            G[n2][n1] -= g

    # Resistors
    for r in resistors:
        a = ep_node.get(f"{r['id']}.a") or ep_node.get(f"{r['id']}.1")
        bb = ep_node.get(f"{r['id']}.b") or ep_node.get(f"{r['id']}.2")
        if a is None or bb is None:
            continue
        stamp_resistor(a, bb, r["ohms"])

    # LEDs as Vf + Rs (piecewise on; assume forward for solve, polarity checked separately)
    led_current: dict[str, float] = {}
    for d in leds:
        a = ep_node.get(f"{d['id']}.a")
        k = ep_node.get(f"{d['id']}.k")
        if a is None or k is None:
            continue
        # Thevenin: series Rs between a and aux, and voltage... simplify: Rs between a-k and inject
        # Use Rs between anode and cathode plus current estimate after solve of resistive network
        # with LED replaced by Rs only first, then I = (Va-Vk - Vf)/Rs if positive else 0
        stamp_resistor(a, k, d["rs"] + 1e-3)

    # Ideal voltage sources via stamping (augmented) — for single supply to gnd:
    # Fix known voltage: for each supply, set pos node voltage = V by modifying equation
    known: dict[int, float] = {0: 0.0}
    for s in supplies:
        pos = ep_node.get(f"{s['id']}.pos")
        if pos is None:
            continue
        known[pos] = float(s.get("volts", norm["supply_voltage"]))

    # Apply known voltages (reduce system)
    free = [i for i in range(n) if i not in known]
    m = len(free)
    if m == 0:
        v = [0.0] * n
        for i, val in known.items():
            v[i] = val
    else:
        A = [[0.0] * m for _ in range(m)]
        rhs = [0.0] * m
        idx = {node: i for i, node in enumerate(free)}
        for i, ni in enumerate(free):
            rhs[i] = b[ni]
            for nj in range(n):
                if nj in known:
                    rhs[i] -= G[ni][nj] * known[nj]
                elif nj in idx:
                    A[i][idx[nj]] += G[ni][nj]
        x = _solve(A, rhs)
        v = [0.0] * n
        for node, val in known.items():
            v[node] = val
        for node, i in idx.items():
            v[node] = x[i]

    # LED currents
    for d in leds:
        a = ep_node.get(f"{d['id']}.a")
        k = ep_node.get(f"{d['id']}.k")
        if a is None or k is None:
            led_current[d["id"]] = 0.0
            continue
        dv = v[a] - v[k]
        i = (dv - d["vf"]) / d["rs"] if dv > d["vf"] else 0.0
        led_current[d["id"]] = i

    # Resistor currents / power
    r_power: dict[str, float] = {}
    r_current: dict[str, float] = {}
    for r in resistors:
        a = ep_node.get(f"{r['id']}.a") or ep_node.get(f"{r['id']}.1")
        bb = ep_node.get(f"{r['id']}.b") or ep_node.get(f"{r['id']}.2")
        if a is None or bb is None:
            continue
        i = abs(v[a] - v[bb]) / max(r["ohms"], 1e-9)
        r_current[r["id"]] = i
        r_power[r["id"]] = i * i * r["ohms"]

    # Short detection: supply pos shorted to gnd with near-zero R path
    short = False
    for s in supplies:
        pos = ep_node.get(f"{s['id']}.pos")
        if pos is not None and abs(v[pos] - float(s.get("volts", norm["supply_voltage"]))) < 1e-6:
            # if any resistor ~0 between pos and gnd
            for r in resistors:
                a = ep_node.get(f"{r['id']}.a") or ep_node.get(f"{r['id']}.1")
                bb = ep_node.get(f"{r['id']}.b") or ep_node.get(f"{r['id']}.2")
                if a is None or bb is None:
                    continue
                if {a, bb} == {pos, 0} and r["ohms"] < 1.0:
                    short = True

    return {
        "nodes": {k: v[i] if i < len(v) else None for k, i in ep_node.items()},
        "led_current_a": led_current,
        "resistor_current_a": r_current,
        "resistor_power_w": r_power,
        "short_circuit": short,
        "ok": True,
    }


def _solve(A: list[list[float]], b: list[float]) -> list[float]:
    """Gaussian elimination with partial pivoting."""
    n = len(b)
    M = [A[i][:] + [b[i]] for i in range(n)]
    for col in range(n):
        piv = max(range(col, n), key=lambda r: abs(M[r][col]))
        if abs(M[piv][col]) < 1e-12:
            continue
        M[col], M[piv] = M[piv], M[col]
        div = M[col][col]
        for j in range(col, n + 1):
            M[col][j] /= div
        for r in range(n):
            if r == col:
                continue
            f = M[r][col]
            for j in range(col, n + 1):
                M[r][j] -= f * M[col][j]
    return [M[i][n] for i in range(n)]
