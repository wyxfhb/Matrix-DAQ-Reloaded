# Author: T. Onkst | Date: 04212026

from __future__ import annotations

from typing import List, Optional, Tuple

try:
    from PySide6.QtCore import Qt, QRectF
    from PySide6.QtGui import QColor, QPainter, QPen, QBrush, QFont, QPainterPath
    from PySide6.QtWidgets import QWidget
except Exception:
    raise

from .cycle_profile_math import CyclePlotSeries, build_expanded_cycle_profile


class CycleChartWidget(QWidget):
    """Lightweight step-schedule chart drawn with QPainter.

    Displays the load profile preview with axis labels and a
    vertical marker showing the current time position.
    """

    _BG = QColor(30, 30, 30)
    _GRID = QColor(60, 60, 60)
    _AXIS_TEXT = QColor(180, 180, 180)
    _STEP_LINE = QColor("#4fc3f7")
    _STEP_FILL = QColor(79, 195, 247, 35)
    _LOOP_MARKER = QColor("#555555")
    _MARKER = QColor(231, 76, 60)
    _MARGIN_L = 48
    _MARGIN_R = 12
    _MARGIN_T = 10
    _MARGIN_B = 24

    def __init__(self, parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        self._schedule: List[Tuple[float, float]] = []
        self._series: List[CyclePlotSeries] = []
        self._loop_boundaries_s: List[float] = []
        self._max_left: float = 100.0
        self._max_right: float = 1.0
        self._has_right_axis: bool = False
        self._duration_s: float = 1.0
        self._position_s: float = 0.0
        self.setMinimumHeight(100)

    def set_schedule(
        self,
        schedule: List[Tuple[float, float]],
        duration_s: float,
        loops: int = 1,
    ) -> None:
        self._schedule = list(schedule)
        profile = build_expanded_cycle_profile(
            [t for t, _ in self._schedule],
            [v for _, v in self._schedule],
            loops=loops,
        )
        self.set_schedule_series(
            [
                CyclePlotSeries(
                    name="Load",
                    times=profile.times,
                    values=profile.loads,
                    axis="left",
                    unit="kW",
                    color="#4fc3f7",
                )
            ],
            max(1.0, profile.total_duration_s, duration_s),
            profile.loop_boundaries_s,
        )

    def set_schedule_series(
        self,
        series: List[CyclePlotSeries],
        duration_s: float,
        loop_boundaries_s: List[float] | None = None,
    ) -> None:
        self._series = list(series)
        self._loop_boundaries_s = list(loop_boundaries_s or [])
        self._duration_s = max(1.0, float(duration_s or 1.0))
        left_vals = [v for s in self._series if s.axis != "right" for v in s.values]
        right_vals = [v for s in self._series if s.axis == "right" for v in s.values]
        self._has_right_axis = bool(right_vals)
        self._max_left = max(left_vals or [100.0]) * 1.1
        if self._max_left < 1.0:
            self._max_left = 100.0
        self._max_right = max(1.0, max(right_vals or [1.0])) * 1.1
        self.update()

    def clear_schedule(self) -> None:
        self._schedule = []
        self._series = []
        self._loop_boundaries_s = []
        self._duration_s = 1.0
        self._position_s = 0.0
        self.update()

    def set_position(self, position_s: float) -> None:
        self._position_s = max(0.0, position_s)
        self.update()

    def paintEvent(self, event) -> None:  # noqa: N802
        if not self._series:
            return
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        w = self.width()
        h = self.height()
        ml = self._MARGIN_L
        mr = 42 if self._has_right_axis else self._MARGIN_R
        mt, mb = self._MARGIN_T, self._MARGIN_B
        plot_w = w - ml - mr
        plot_h = h - mt - mb
        if plot_w < 10 or plot_h < 10:
            p.end()
            return

        p.fillRect(0, 0, w, h, self._BG)

        def tx(t: float) -> float:
            return ml + (t / self._duration_s) * plot_w

        def ty(v: float, axis: str) -> float:
            scale = self._max_right if axis == "right" else self._max_left
            return mt + plot_h - (v / max(0.001, scale)) * plot_h

        # Grid lines (3 horizontal)
        pen_grid = QPen(self._GRID, 1, Qt.PenStyle.DotLine)
        p.setPen(pen_grid)
        for i in range(1, 4):
            gy = mt + plot_h * (1.0 - i / 4.0)
            p.drawLine(int(ml), int(gy), int(ml + plot_w), int(gy))

        # Axis labels
        font = QFont("Segoe UI", 7)
        p.setFont(font)
        p.setPen(QPen(self._AXIS_TEXT))
        for i in range(5):
            frac = i / 4.0
            val = self._max_left * frac
            label = f"{val:.0f}"
            yl = mt + plot_h * (1.0 - frac)
            p.drawText(QRectF(0, yl - 8, ml - 4, 16), Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter, label)
            if self._has_right_axis:
                rv = self._max_right * frac
                rlabel = f"{rv:.0f}" if rv > 1.1 else f"{rv:.1f}"
                p.drawText(
                    QRectF(ml + plot_w + 4, yl - 8, mr - 6, 16),
                    Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter,
                    rlabel,
                )

        # Time labels along bottom
        n_labels = min(5, max(2, int(self._duration_s / 60) + 1))
        for i in range(n_labels + 1):
            frac = i / n_labels
            t_val = self._duration_s * frac
            xl = tx(t_val)
            if t_val >= 3600:
                lbl = f"{t_val/3600:.1f}h"
            elif t_val >= 60:
                lbl = f"{t_val/60:.0f}m"
            else:
                lbl = f"{t_val:.0f}s"
            p.drawText(QRectF(xl - 20, mt + plot_h + 2, 40, 18), Qt.AlignmentFlag.AlignCenter, lbl)

        # Step lines
        legend_x = ml + 6
        legend_y = mt + 4
        for idx, series in enumerate(self._series):
            path = QPainterPath()
            baseline_y = ty(0.0, series.axis)
            first = True
            for t, v in zip(series.times, series.values):
                x = tx(t)
                y = ty(v, series.axis)
                if first:
                    path.moveTo(x, y)
                    first = False
                else:
                    path.lineTo(x, path.currentPosition().y())
                    path.lineTo(x, y)
            if series.times:
                path.lineTo(tx(self._duration_s), path.currentPosition().y())

            color = QColor(series.color)
            if idx == 0 and series.times:
                fill_path = QPainterPath(path)
                fill_path.lineTo(tx(self._duration_s), baseline_y)
                fill_path.lineTo(tx(series.times[0]), baseline_y)
                fill = QColor(color)
                fill.setAlpha(28)
                p.setPen(Qt.PenStyle.NoPen)
                p.setBrush(QBrush(fill))
                p.drawPath(fill_path)
            p.setPen(QPen(color, 2))
            p.setBrush(Qt.BrushStyle.NoBrush)
            p.drawPath(path)

            p.drawLine(legend_x, legend_y + idx * 12 + 6, legend_x + 12, legend_y + idx * 12 + 6)
            p.setPen(QPen(self._AXIS_TEXT))
            p.drawText(QRectF(legend_x + 16, legend_y + idx * 12, 160, 12), Qt.AlignmentFlag.AlignLeft, series.name)

        # Loop boundaries match the dashed dividers used in the config preview.
        if self._loop_boundaries_s:
            p.setPen(QPen(self._LOOP_MARKER, 1, Qt.PenStyle.DashLine))
            for boundary_s in self._loop_boundaries_s:
                bx = tx(boundary_s)
                p.drawLine(int(bx), int(mt), int(bx), int(mt + plot_h))

        # Position marker
        mx = tx(min(self._position_s, self._duration_s))
        pen_marker = QPen(self._MARKER, 2)
        p.setPen(pen_marker)
        p.drawLine(int(mx), int(mt), int(mx), int(mt + plot_h))

        # Axes border
        p.setPen(QPen(self._AXIS_TEXT, 1))
        p.drawLine(int(ml), int(mt), int(ml), int(mt + plot_h))
        p.drawLine(int(ml), int(mt + plot_h), int(ml + plot_w), int(mt + plot_h))
        if self._has_right_axis:
            p.drawLine(int(ml + plot_w), int(mt), int(ml + plot_w), int(mt + plot_h))

        p.end()
