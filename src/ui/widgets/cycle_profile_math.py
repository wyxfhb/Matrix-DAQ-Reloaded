# Author: T. Onkst | Date: 05072026

from __future__ import annotations

from dataclasses import dataclass
from typing import Dict, List, Sequence


@dataclass(frozen=True)
class ExpandedCycleProfile:
    times: List[float]
    loads: List[float]
    cycle_len_s: float
    total_duration_s: float
    loop_boundaries_s: List[float]


@dataclass(frozen=True)
class CyclePlotSeries:
    name: str
    times: List[float]
    values: List[float]
    axis: str = "left"
    unit: str = ""
    color: str = "#4fc3f7"


_COLORS = [
    "#4fc3f7",
    "#f39c12",
    "#2ecc71",
    "#e74c3c",
    "#9b59b6",
    "#f1c40f",
    "#1abc9c",
    "#e67e22",
]


def build_expanded_cycle_profile(
    times: Sequence[float],
    loads: Sequence[float],
    loops: int = 1,
) -> ExpandedCycleProfile:
    """Build the same step-expanded cycle profile used by the config preview."""
    pairs = [(float(t), float(v)) for t, v in zip(times, loads)]
    if not pairs:
        return ExpandedCycleProfile([], [], 0.0, 0.0, [])

    loops = max(1, int(loops))
    t0 = pairs[0][0]
    cycle_len = pairs[-1][0] - t0 if len(pairs) > 1 else 0.0

    step_t: List[float] = []
    step_v: List[float] = []
    for i, (t, v) in enumerate(pairs):
        rel_t = t - t0
        if i > 0:
            step_t.append(rel_t)
            step_v.append(pairs[i - 1][1])
        step_t.append(rel_t)
        step_v.append(v)

    all_t: List[float] = []
    all_v: List[float] = []
    for loop_i in range(loops):
        offset = loop_i * cycle_len
        for t, v in zip(step_t, step_v):
            all_t.append(t + offset)
            all_v.append(v)

    loop_boundaries = [li * cycle_len for li in range(1, loops)]
    total_duration = max(all_t) if all_t else 0.0
    return ExpandedCycleProfile(all_t, all_v, cycle_len, total_duration, loop_boundaries)


def build_expanded_cycle_profiles(
    times: Sequence[float],
    columns: Dict[str, Sequence[float]],
    outputs: Sequence[Dict[str, str]],
    loops: int = 1,
) -> tuple[List[CyclePlotSeries], float, List[float]]:
    series: List[CyclePlotSeries] = []
    total_duration = 0.0
    loop_boundaries: List[float] = []
    for idx, mapping in enumerate(outputs):
        col = str(mapping.get("csv_column", ""))
        if not col or col not in columns:
            continue
        typ = str(mapping.get("type", "")).lower()
        label = str(mapping.get("alias") or col)
        if typ == "loadbank":
            label = f"{col} (loadbank)"
        unit = "kW" if typ == "loadbank" else ("bool" if typ == "nidaq_do" else "")
        axis = "right" if typ == "nidaq_do" else "left"
        profile = build_expanded_cycle_profile(times, columns[col], loops=loops)
        total_duration = max(total_duration, profile.total_duration_s)
        if profile.loop_boundaries_s:
            loop_boundaries = profile.loop_boundaries_s
        series.append(
            CyclePlotSeries(
                name=label,
                times=profile.times,
                values=profile.loads,
                axis=axis,
                unit=unit,
                color=_COLORS[idx % len(_COLORS)],
            )
        )
    return series, total_duration, loop_boundaries
