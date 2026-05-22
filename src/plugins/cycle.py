# Author: T. Onkst | Date: 04212026

from __future__ import annotations

import csv
import time
from typing import Any, Dict, List, Set
from pathlib import Path

from .base import BasePlugin, PluginStatus

_STATE_IDLE = "idle"
_STATE_RUNNING = "running"
_STATE_PAUSED = "paused"
_STATE_COMPLETE = "complete"

_STATE_INT = {_STATE_IDLE: 0, _STATE_RUNNING: 1, _STATE_PAUSED: 2, _STATE_COMPLETE: 3}

_PUBLIC_TELEMETRY_UNITS = {
    "iDG_Cyc": "",
    "iTM_Cyc": "s",
    "iPO_Cyc": "kW",
    "iPC_Cyc": "%",
}


class CyclePlugin(BasePlugin):
    id = "Cycle"

    def __init__(self, *args, **kwargs) -> None:
        super().__init__(*args, **kwargs)
        self._schedule: List[tuple[float, Dict[str, float]]] = []
        self._outputs: List[Dict[str, str]] = []
        self._legacy_load_column: str = "Load"
        self._csv_headers: List[str] = []
        self._validation_message: str = ""
        self._t0: float = 0.0
        self._loop_len: float = 0.0
        self._loops_total: int = 1
        self._state: str = _STATE_IDLE
        self._paused: bool = False
        self._pause_elapsed: float = 0.0
        self._last_setpoint: float = 0.0
        self._last_values: Dict[str, float] = {}
        self._start_with_test: bool = False

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    def configure(self) -> None:
        self._schedule = []
        self._outputs = []
        self._csv_headers = []
        self._validation_message = ""
        self._loop_len = 0.0
        src = self.config.get("source") or {}
        cols = src.get("columns") or {}
        if isinstance(cols, dict):
            self._legacy_load_column = str(cols.get("load", "Load") or "Load")
        else:
            self._legacy_load_column = "Load"
        self._outputs = self._normalize_outputs(self.config.get("outputs"))
        csv_path = src.get("csv_path")
        if csv_path:
            p = Path(csv_path)
            candidates = [p, (self.configs_dir / p).resolve(), (self.configs_dir.parent / p).resolve()]
            for c in candidates:
                if c.exists():
                    self._schedule, self._csv_headers = self._read_csv(c, self._outputs)
                    break
            data_headers = self._csv_headers[1:] if self._csv_headers else []
            time_header = self._csv_headers[0] if self._csv_headers else ""
            missing = [
                o.get("csv_column", "")
                for o in self._outputs
                if o.get("csv_column", "") and o.get("csv_column", "") not in data_headers
            ]
            if missing:
                self._validation_message = "missing cycle CSV column(s): " + ", ".join(sorted(set(missing)))
            if any(o.get("csv_column", "") == time_header for o in self._outputs):
                self._validation_message = f"cycle output cannot map first/time column: {time_header}"
        if self._schedule:
            self._loop_len = max(t for t, _ in self._schedule)
            self._last_values = self._zero_values()
        exec_cfg = self.config.get("execution") or {}
        self._loops_total = max(1, int(exec_cfg.get("loops_total", 1)))
        self._start_with_test = bool(exec_cfg.get("start_with_test", False))

    def validate(self) -> PluginStatus:
        if not isinstance(self.config.get("source", {}), dict):
            return PluginStatus(ok=False, message="cycle source block required")
        if self._validation_message:
            return PluginStatus(ok=False, message=self._validation_message)
        if not self._outputs:
            return PluginStatus(ok=False, message="cycle outputs block is empty")
        if not self._schedule:
            return PluginStatus(ok=False, message="cycle schedule is empty or unreadable")
        return PluginStatus(ok=True)

    def start(self) -> None:
        self._state = _STATE_IDLE
        self._paused = False
        self._pause_elapsed = 0.0
        self._last_setpoint = 0.0
        self._last_values = self._zero_values()
        self._t0 = 0.0

    def stop(self) -> None:
        self._state = _STATE_IDLE
        self._paused = False

    def aliases(self) -> Set[str]:
        aliases = set(_PUBLIC_TELEMETRY_UNITS) if self._expose_operator_aliases() else set()
        if self._expose_debug_channels():
            aliases |= {
                "Cycle/state", "Cycle/position_s", "Cycle/setpoint_kw",
                "Cycle/loop_current", "Cycle/loop_total", "Cycle/progress_pct",
                "Cycle/schedule_len_s", "Cycle/elapsed_s",
            }
            for out in self._outputs:
                label = self._output_label(out)
                if label:
                    aliases.add(f"Cycle/output/{label}")
        return aliases

    def units(self) -> Dict[str, str]:
        units = dict(_PUBLIC_TELEMETRY_UNITS) if self._expose_operator_aliases() else {}
        if self._expose_debug_channels():
            units.update({
                "Cycle/state": "",
                "Cycle/position_s": "s",
                "Cycle/setpoint_kw": "kW",
                "Cycle/loop_current": "",
                "Cycle/loop_total": "",
                "Cycle/progress_pct": "%",
                "Cycle/schedule_len_s": "s",
                "Cycle/elapsed_s": "s",
            })
            for out in self._outputs:
                label = self._output_label(out)
                typ = str(out.get("type", "")).lower()
                if label:
                    units[f"Cycle/output/{label}"] = "kW" if typ == "loadbank" else ("bool" if typ == "nidaq_do" else "")
        return units

    # ------------------------------------------------------------------
    # Play / Pause / Seek / Loops
    # ------------------------------------------------------------------

    def play(self) -> None:
        """Start or resume the cycle. If complete, restart from the beginning."""
        if self._state == _STATE_COMPLETE:
            self._t0 = time.time()
            self._paused = False
            self._pause_elapsed = 0.0
            self._last_setpoint = 0.0
            self._last_values = self._zero_values()
            self._state = _STATE_RUNNING
            return
        if self._state == _STATE_PAUSED:
            self._t0 = time.time() - self._pause_elapsed
            self._paused = False
            self._state = _STATE_RUNNING
        elif self._state == _STATE_IDLE:
            self._t0 = time.time()
            self._paused = False
            self._pause_elapsed = 0.0
            self._last_setpoint = 0.0
            self._last_values = self._zero_values()
            self._state = _STATE_RUNNING

    def pause(self) -> None:
        """Freeze the cycle at its current position."""
        if self._state != _STATE_RUNNING:
            return
        self._pause_elapsed = time.time() - self._t0
        self._paused = True
        self._state = _STATE_PAUSED

    def seek(self, time_s: float) -> None:
        """Jump to a specific time in the schedule (only when paused)."""
        if self._state != _STATE_PAUSED:
            return
        total_dur = self._loop_len * max(self._loops_total, 1)
        self._pause_elapsed = max(0.0, min(float(time_s), total_dur))

    def set_loops(self, n: int) -> None:
        """Update the total loop count at runtime."""
        self._loops_total = max(1, int(n))
        if self._state == _STATE_COMPLETE:
            elapsed = self._elapsed_s()
            total_dur = self._loop_len * self._loops_total
            if elapsed < total_dur:
                self._state = _STATE_PAUSED
                self._paused = True
                self._pause_elapsed = elapsed

    def set_start_with_test(self, enabled: bool) -> None:
        self._start_with_test = bool(enabled)

    def is_ready(self) -> bool:
        return bool(self._schedule) and self._state != _STATE_COMPLETE

    def is_complete(self) -> bool:
        return self._state == _STATE_COMPLETE

    @property
    def start_with_test(self) -> bool:
        return self._start_with_test

    @property
    def schedule(self) -> List[tuple[float, float]]:
        col = self.loadbank_column
        return [(t, float(values.get(col, 0.0))) for t, values in self._schedule] if col else []

    @property
    def output_mappings(self) -> List[Dict[str, str]]:
        return [dict(o) for o in self._outputs]

    @property
    def loadbank_column(self) -> str:
        for out in self._outputs:
            if str(out.get("type", "")).lower() == "loadbank":
                return str(out.get("csv_column", ""))
        return ""

    def has_loadbank_output(self) -> bool:
        return bool(self.loadbank_column)

    # ------------------------------------------------------------------
    # Setpoint evaluation
    # ------------------------------------------------------------------

    def current_setpoint_kw(self) -> float:
        vals = self.current_values()
        col = self.loadbank_column
        val = float(vals.get(col, 0.0)) if col else 0.0
        self._last_setpoint = val
        return val

    def current_values(self) -> Dict[str, float]:
        if self._state == _STATE_PAUSED:
            return dict(self._last_values)
        if self._state != _STATE_RUNNING or not self._schedule:
            return dict(self._last_values)
        pos = self._current_loop_pos()
        vals = self._interp_schedule(pos)
        self._last_values = dict(vals)
        col = self.loadbank_column
        self._last_setpoint = float(vals.get(col, 0.0)) if col else 0.0
        return dict(vals)

    def _elapsed_s(self) -> float:
        if self._paused:
            return self._pause_elapsed
        if self._t0 <= 0.0:
            return 0.0
        return time.time() - self._t0

    def _current_loop_pos(self) -> float:
        """Position within the current loop (seconds)."""
        elapsed = self._elapsed_s()
        total_dur = self._loop_len * max(self._loops_total, 1)
        if self._loop_len <= 0:
            return 0.0
        if elapsed >= total_dur and self._loops_total >= 1:
            self._state = _STATE_COMPLETE
            return self._loop_len
        if self._loops_total > 1:
            return elapsed % self._loop_len
        return min(elapsed, self._loop_len)

    def _current_loop_number(self) -> int:
        """1-based loop index."""
        elapsed = self._elapsed_s()
        if self._loop_len <= 0:
            return 1
        return min(int(elapsed // self._loop_len) + 1, self._loops_total)

    def _interp_schedule(self, pos: float) -> Dict[str, float]:
        last_vals = self._zero_values()
        for t, values in self._schedule:
            if pos >= t:
                last_vals = dict(values)
            else:
                break
        return last_vals

    # ------------------------------------------------------------------
    # Telemetry
    # ------------------------------------------------------------------

    def _telemetry_cfg(self) -> Dict[str, Any]:
        cfg = self.config.get("telemetry") or {}
        return cfg if isinstance(cfg, dict) else {}

    def _expose_operator_aliases(self) -> bool:
        return bool(self._telemetry_cfg().get("expose_operator_aliases", True))

    def _expose_debug_channels(self) -> bool:
        return bool(self._telemetry_cfg().get("expose_debug_channels", False))

    def simulate_step(self, _vals: Dict[str, Any] | None = None) -> Dict[str, Any]:
        status = self._build_status_fields()
        out: Dict[str, Any] = {}
        if self._expose_operator_aliases():
            out.update(self._public_telemetry(status))
        if self._expose_debug_channels():
            out.update(status.get("debug_values", {}))
        return out

    def status_snapshot(self) -> Dict[str, Any]:
        status = self._build_status_fields()
        return {
            "state": status["state"],
            "state_name": status["state_name"],
            "position_s": status["position_s"],
            "setpoint_kw": status["setpoint_kw"],
            "loop_current": status["loop_current"],
            "loop_total": status["loop_total"],
            "progress_pct": status["progress_pct"],
            "schedule_len_s": status["schedule_len_s"],
            "elapsed_s": status["elapsed_s"],
            "outputs": dict(status.get("outputs", {})),
        }

    def _public_telemetry(self, status: Dict[str, Any]) -> Dict[str, Any]:
        return {
            "iDG_Cyc": float(status["state"]),
            "iTM_Cyc": float(status["position_s"]),
            "iPO_Cyc": float(status["setpoint_kw"]),
            "iPC_Cyc": float(status["progress_pct"]),
        }

    def _build_status_fields(self) -> Dict[str, Any]:
        elapsed = self._elapsed_s()
        # Values must be computed while still running: _current_loop_pos() can set
        # complete first, which would otherwise leave outputs stuck on the prior step.
        values = self.current_values()
        col = self.loadbank_column
        sp = float(values.get(col, 0.0)) if col else 0.0
        if self._state in (_STATE_RUNNING, _STATE_PAUSED):
            pos = self._current_loop_pos()
        elif self._state == _STATE_COMPLETE:
            pos = self._loop_len
        else:
            pos = 0.0
        loop_cur = self._current_loop_number() if self._state in (_STATE_RUNNING, _STATE_PAUSED, _STATE_COMPLETE) else 0
        total_dur = self._loop_len * max(self._loops_total, 1)
        progress = min(100.0, (elapsed / total_dur * 100.0) if total_dur > 0 else 0.0)
        debug_values = {
            "Cycle/state": float(_STATE_INT.get(self._state, 0)),
            "Cycle/position_s": round(pos, 2),
            "Cycle/setpoint_kw": round(sp, 2),
            "Cycle/loop_current": float(loop_cur),
            "Cycle/loop_total": float(self._loops_total),
            "Cycle/progress_pct": round(progress, 1),
            "Cycle/schedule_len_s": round(self._loop_len, 2),
            "Cycle/elapsed_s": round(elapsed, 2),
        }
        for mapping in self._outputs:
            label = self._output_label(mapping)
            col_name = str(mapping.get("csv_column", ""))
            if label and col_name:
                debug_values[f"Cycle/output/{label}"] = round(float(values.get(col_name, 0.0)), 4)
        outputs = {
            self._output_label(mapping): round(float(values.get(str(mapping.get("csv_column", "")), 0.0)), 4)
            for mapping in self._outputs
            if self._output_label(mapping) and mapping.get("csv_column")
        }
        return {
            "state": int(_STATE_INT.get(self._state, 0)),
            "state_name": self._state,
            "position_s": round(pos, 2),
            "setpoint_kw": round(sp, 2),
            "loop_current": int(loop_cur),
            "loop_total": int(self._loops_total),
            "progress_pct": round(progress, 1),
            "schedule_len_s": round(self._loop_len, 2),
            "elapsed_s": round(elapsed, 2),
            "outputs": outputs,
            "debug_values": debug_values,
        }

    # ------------------------------------------------------------------
    # CSV loader
    # ------------------------------------------------------------------

    @staticmethod
    def _read_csv(
        path: Path,
        outputs: List[Dict[str, str]],
    ) -> tuple[List[tuple[float, Dict[str, float]]], List[str]]:
        rows: List[tuple[float, Dict[str, float]]] = []
        with path.open("r", encoding="utf-8-sig", newline="") as f:
            reader = csv.DictReader(f)
            headers = [str(h or "").strip() for h in (reader.fieldnames or [])]
            if not headers:
                return rows, []
            reader.fieldnames = headers
            time_column = headers[0]
            for row in reader:
                try:
                    raw_t = row.get(time_column, "")
                    if raw_t is None or str(raw_t).strip().startswith("#"):
                        continue
                    t = float(raw_t)
                    vals: Dict[str, float] = {}
                    for out in outputs:
                        col = str(out.get("csv_column", ""))
                        vals[col] = float(row.get(col, 0.0) or 0.0)
                    rows.append((t, vals))
                except Exception:
                    continue
        rows.sort(key=lambda x: x[0])
        return rows, headers

    def _normalize_outputs(self, raw: Any) -> List[Dict[str, str]]:
        outs: List[Dict[str, str]] = []
        if isinstance(raw, list):
            for item in raw:
                if not isinstance(item, dict):
                    continue
                csv_col = str(item.get("csv_column", "") or "").strip()
                typ = str(item.get("type", "") or "").strip().lower()
                alias = str(item.get("alias", "") or "").strip()
                if not csv_col or typ not in {"loadbank", "nidaq_do", "nidaq_ao"}:
                    continue
                out = {"csv_column": csv_col, "type": typ}
                if alias:
                    out["alias"] = alias
                outs.append(out)
        if outs:
            return outs
        return [{"csv_column": self._legacy_load_column or "Load", "type": "loadbank"}]

    def _zero_values(self) -> Dict[str, float]:
        return {str(out.get("csv_column", "")): 0.0 for out in self._outputs if out.get("csv_column")}

    def _output_label(self, mapping: Dict[str, str]) -> str:
        typ = str(mapping.get("type", "")).lower()
        if typ in {"nidaq_do", "nidaq_ao"} and mapping.get("alias"):
            return str(mapping.get("alias"))
        return str(mapping.get("csv_column", ""))
