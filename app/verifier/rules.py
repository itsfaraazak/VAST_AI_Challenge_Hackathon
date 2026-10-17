"""Deterministic rule checks — no LLM."""
from __future__ import annotations


def check_rules(norm: dict, sim: dict) -> list[dict]:
    findings: list[dict] = []
    comps = {c["id"]: c for c in norm["components"]}
    leds = [c for c in comps.values() if c["type"] == "led"]
    resistors = [c for c in comps.values() if c["type"] == "resistor"]
    supplies = [c for c in comps.values() if c["type"] == "supply"]

    # Build adjacency of component ids via nets
    neighbors: dict[str, set[str]] = {cid: set() for cid in comps}
    endpoints_by_comp: dict[str, list[str]] = {cid: [] for cid in comps}
    all_eps: set[str] = set()
    for net in norm["nets"]:
        ids = []
        for e in net:
            all_eps.add(e)
            cid = e.split(".", 1)[0]
            if cid in comps:
                endpoints_by_comp[cid].append(e)
                ids.append(cid)
        for a in ids:
            for b in ids:
                if a != b:
                    neighbors[a].add(b)

    for d in leds:
        # series resistor present?
        has_r = any(neighbors[d["id"]] & {r["id"] for r in resistors})
        if not has_r:
            findings.append(_f(
                "led_no_series_resistor", "critical", "LED_NO_SERIES_R",
                f"LED {d['id']} has no series resistor.",
                {"led": d["id"]},
            ))
        # polarity: anode sharing a net with supply negative ⇒ reversed
        a_ep = f"{d['id']}.a"
        neg_eps = {f"{s['id']}.neg" for s in supplies} | {"gnd.gnd", "gnd.1"}
        anode_on_neg = any(
            a_ep in net and any(e in neg_eps for e in net)
            for net in norm["nets"]
        )
        if anode_on_neg:
            findings.append(_f(
                "led_reversed", "critical", "LED_REVERSED",
                f"LED {d['id']} appears reverse-biased (anode toward ground).",
                {"led": d["id"]},
            ))
        i = sim.get("led_current_a", {}).get(d["id"], 0.0)
        if i > 0.020:
            findings.append(_f(
                "led_overcurrent", "critical", "LED_CURRENT_GT_20MA",
                f"LED {d['id']} current {i*1000:.1f} mA exceeds 20 mA.",
                {"led": d["id"], "amps": i},
            ))

    if sim.get("short_circuit"):
        findings.append(_f(
            "supply_short", "critical", "SUPPLY_SHORT",
            "Near-short across the supply.",
            {},
        ))
    # also detect direct pos-neg net
    for net in norm["nets"]:
        kinds = set()
        for e in net:
            if e.endswith(".pos"):
                kinds.add("pos")
            if e.endswith(".neg"):
                kinds.add("neg")
        if kinds == {"pos", "neg"} and len(net) <= 3:
            # only if no resistor/led in the same net
            ids = {e.split(".", 1)[0] for e in net}
            if not any(comps.get(i, {}).get("type") in ("resistor", "led") for i in ids):
                findings.append(_f(
                    "supply_short", "critical", "SUPPLY_SHORT",
                    "Supply positive and negative appear directly connected.",
                    {"net": net},
                ))

    # floating nets: component pin never appears
    for c in comps.values():
        if c["type"] in ("wire",):
            continue
        pins = endpoints_by_comp.get(c["id"]) or []
        if not pins:
            findings.append(_f(
                f"floating_{c['id']}", "warning", "FLOATING_NET",
                f"Component {c['id']} has no connected nets.",
                {"component": c["id"]},
            ))

    for r in resistors:
        p = sim.get("resistor_power_w", {}).get(r["id"], 0.0)
        rating = r.get("power_w", 0.25)
        if p > rating:
            findings.append(_f(
                f"resistor_power_{r['id']}", "warning", "RESISTOR_OVERPOWER",
                f"Resistor {r['id']} dissipation {p:.3f} W exceeds rating {rating} W.",
                {"resistor": r["id"], "watts": p, "rating": rating},
            ))

    # dedupe by rule+message
    seen = set()
    uniq = []
    for f in findings:
        key = (f["rule"], f["message"])
        if key in seen:
            continue
        seen.add(key)
        uniq.append(f)
    return uniq


def _f(fid: str, severity: str, rule: str, message: str, evidence: dict) -> dict:
    return {"id": fid, "severity": severity, "rule": rule, "message": message, "evidence": evidence}
