"""Verifier entrypoint: twin -> findings + simulation + Z3 badge."""
from __future__ import annotations

from verifier.mna import solve_dc
from verifier.parser import normalize
from verifier.rules import check_rules
from verifier.z3check import check_led_current_invariant


def verify_twin(twin: dict, supply_voltage: float = 5.0) -> dict:
    if not isinstance(twin, dict) or "components" not in twin or "nets" not in twin:
        return {
            "ok": False,
            "findings": [{
                "id": "invalid_twin",
                "severity": "critical",
                "rule": "INVALID_TWIN",
                "message": "Twin JSON missing components/nets.",
                "evidence": {},
            }],
            "simulation": None,
            "z3": None,
            "badge": "simulation-verified",
        }
    norm = normalize(twin, supply_voltage=supply_voltage)
    sim = solve_dc(norm)
    findings = check_rules(norm, sim)
    z3r = check_led_current_invariant(norm)
    badge = z3r["badge"] if z3r.get("proved") else "simulation-verified"
    # Only claim formally verified when Z3 proved
    if not z3r.get("proved"):
        badge = "simulation-verified"
    else:
        badge = "formally verified"
    return {
        "ok": True,
        "findings": findings,
        "simulation": sim,
        "z3": z3r,
        "badge": badge,
        "normalized": norm,
    }
