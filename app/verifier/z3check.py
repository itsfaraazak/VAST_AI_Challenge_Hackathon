"""Z3 invariant: for every supply V in [3,12], LED current stays below limit."""
from __future__ import annotations

LED_LIMIT = 0.020


def check_led_current_invariant(norm: dict, limit: float = LED_LIMIT) -> dict:
    """
    Label 'formally verified' only when Z3 returns unsat for the negation.
    Otherwise 'simulation-verified' (or unavailable).
    """
    try:
        import z3  # type: ignore
    except Exception:  # noqa: BLE001
        return {
            "available": False,
            "proved": False,
            "badge": "simulation-verified",
            "counterexample_v": None,
            "detail": "z3_missing",
        }

    leds = [c for c in norm["components"] if c["type"] == "led"]
    resistors = [c for c in norm["components"] if c["type"] == "resistor"]
    if not leds:
        return {
            "available": True,
            "proved": True,
            "badge": "formally verified",
            "counterexample_v": None,
            "detail": "no_led",
        }
    # Simplified series model: I = max(0, (V - Vf) / Rseries)
    # Rseries = sum of resistor ohms neighboring any LED (approx all resistors)
    rsum = sum(r["ohms"] for r in resistors) if resistors else 0.0
    if rsum <= 0:
        # no resistor → overcurrent for V > Vf
        return {
            "available": True,
            "proved": False,
            "badge": "simulation-verified",
            "counterexample_v": 5.0,
            "detail": "no_series_r",
        }
    vf = max(d["vf"] for d in leds)
    V = z3.Real("V")
    I = (V - vf) / rsum
    # Negation of invariant: exists V in [3,12] with I > limit
    s = z3.Solver()
    s.add(V >= 3, V <= 12, I > limit)
    res = s.check()
    if res == z3.unsat:
        return {
            "available": True,
            "proved": True,
            "badge": "formally verified",
            "counterexample_v": None,
            "detail": "unsat",
        }
    if res == z3.sat:
        m = s.model()
        v = m[V]
        try:
            cex = float(v.as_decimal(6).rstrip("?"))
        except Exception:  # noqa: BLE001
            cex = float(eval(str(v)))  # noqa: S307 — z3 fraction string
        return {
            "available": True,
            "proved": False,
            "badge": "simulation-verified",
            "counterexample_v": cex,
            "detail": "sat",
        }
    return {
        "available": True,
        "proved": False,
        "badge": "simulation-verified",
        "counterexample_v": None,
        "detail": "unknown",
    }
