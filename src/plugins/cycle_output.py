# Author: T. Onkst | Date: 05222026

from __future__ import annotations

from typing import Any, Dict, Tuple


def _cycle_outputs(cycle: Any) -> list[dict[str, str]]:
    try:
        raw = getattr(cycle, "output_mappings", [])
        return [dict(x) for x in raw if isinstance(x, dict)]
    except Exception:
        return []


def _cycle_has_loadbank_output(cycle: Any) -> bool:
    try:
        fn = getattr(cycle, "has_loadbank_output", None)
        if callable(fn):
            return bool(fn())
    except Exception:
        pass
    return any(str(o.get("type", "")).lower() == "loadbank" for o in _cycle_outputs(cycle))


def cycle_start_actions(orchestrator: Any, cycle: Any, *, source: str) -> bool:
    """Single definition of cycle start side effects.

    Load bank cycles still require Matrix control and enable Master Load before
    play. DO/AO-only cycles just play.
    """
    if _cycle_has_loadbank_output(cycle):
        lb = orchestrator.plugins.get("LoadBank") if orchestrator._plugin_enabled.get("LoadBank", True) else None
        if lb is None:
            print(f"[WARN] Cycle {source} ignored: loadbank output configured but LoadBank plugin is not present")
            return False
        if not orchestrator._loadbank_has_matrix_control(lb):
            print(f"[WARN] Cycle {source} ignored: enable Matrix loadbank control first")
            return False
        lb.command_master_load(True)
        print(f"[CYCLE->LB] Master Load enabled for cycle ({source})")
    try:
        orchestrator._cycle_output_driver.reset()
    except Exception:
        pass
    cycle.play()
    print(f"[INFO] Cycle: play ({source})")
    return True


class CycleOutputDriver:
    """Apply cycle output values to their hardware targets, change-only."""

    def __init__(self) -> None:
        self._last_sent: Dict[Tuple[str, str], float] = {}

    def reset(self) -> None:
        self._last_sent.clear()

    def apply(self, orchestrator: Any, cycle: Any, *, was_running: bool = False) -> None:
        state = str(getattr(cycle, "_state", "idle")).lower()
        if state != "running" and not was_running:
            if state != "paused":
                self.reset()
            return
        try:
            values = getattr(cycle, "current_values")()
        except Exception:
            return
        outputs = _cycle_outputs(cycle)
        for out in outputs:
            typ = str(out.get("type", "")).lower()
            csv_col = str(out.get("csv_column", ""))
            if not csv_col:
                continue
            try:
                value = float(values.get(csv_col, 0.0))
            except Exception:
                value = 0.0
            if typ == "loadbank":
                self._apply_loadbank(orchestrator, csv_col, value)
            elif typ == "nidaq_do":
                self._apply_do(orchestrator, out, value)
            elif typ == "nidaq_ao":
                self._apply_ao(orchestrator, out, value)

    def _changed(self, key: Tuple[str, str], value: float) -> bool:
        old = self._last_sent.get(key)
        if old is not None and old == value:
            return False
        self._last_sent[key] = value
        return True

    def _apply_loadbank(self, orchestrator: Any, csv_col: str, value: float) -> None:
        lb = orchestrator.plugins.get("LoadBank") if orchestrator._plugin_enabled.get("LoadBank", True) else None
        if lb is None or not orchestrator._loadbank_has_matrix_control(lb):
            return
        key = ("loadbank", csv_col)
        if not self._changed(key, value):
            return
        lb.command_setpoint_kw(value)
        print(f"[CYCLE->LB] {csv_col} setpoint -> {value} kW")

    def _apply_do(self, orchestrator: Any, out: dict[str, str], value: float) -> None:
        nidaq = orchestrator.plugins.get("NI_DAQ") if orchestrator._plugin_enabled.get("NI_DAQ", True) else None
        alias = str(out.get("alias", ""))
        if nidaq is None or not alias:
            return
        state = 1.0 if bool(int(round(value))) else 0.0
        key = ("nidaq_do", alias)
        if not self._changed(key, state):
            return
        getattr(nidaq, "write_do")(alias, int(state))
        print(f"[CYCLE->DO] {alias} -> {int(state)}")

    def _apply_ao(self, orchestrator: Any, out: dict[str, str], value: float) -> None:
        nidaq = orchestrator.plugins.get("NI_DAQ") if orchestrator._plugin_enabled.get("NI_DAQ", True) else None
        alias = str(out.get("alias", ""))
        if nidaq is None or not alias:
            return
        key = ("nidaq_ao", alias)
        if not self._changed(key, value):
            return
        getattr(nidaq, "write_ao")(alias, value)
        print(f"[CYCLE->AO] {alias} -> {value}")
