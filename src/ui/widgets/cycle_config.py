# Author: T. Onkst | Date: 05222026

from __future__ import annotations

import csv
import io
import json
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

try:
    from PySide6.QtCore import QMargins, QPointF, Qt, QTimer
    from PySide6.QtGui import QColor, QFont, QPainter, QPen
    from PySide6.QtWidgets import (
        QAbstractItemView,
        QCheckBox,
        QComboBox,
        QDialog,
        QDialogButtonBox,
        QFileDialog,
        QFormLayout,
        QGroupBox,
        QHBoxLayout,
        QHeaderView,
        QLabel,
        QLineEdit,
        QMessageBox,
        QPushButton,
        QSpinBox,
        QTableWidget,
        QTableWidgetItem,
        QVBoxLayout,
    )
except Exception:
    raise

try:
    from PySide6.QtCharts import QChart, QChartView, QLineSeries, QValueAxis
    _HAS_CHARTS = True
except Exception:
    _HAS_CHARTS = False

from .cycle_profile_math import CyclePlotSeries, build_expanded_cycle_profiles
from .nidaq_alias_picker import AliasPickerDialog


_OUTPUT_TYPES = ["loadbank", "nidaq_do", "nidaq_ao"]


class CycleConfigDialog(QDialog):
    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.setWindowTitle("Configure Cycle")
        self.resize(840, 680)
        self._project_root = Path(__file__).resolve().parents[3]
        self._cfg_path = self._project_root / "configs" / "cycle.yaml"
        self._cfg: Dict[str, Any] = {}
        self._series_refs: list = []
        self._csv_headers: List[str] = []
        self._loadbank_setpoint_alias = self._loadbank_setpoint_alias_from_config()
        self._init_ui()
        self._load(defer_preview=True)

    # ------------------------------------------------------------------
    # UI
    # ------------------------------------------------------------------

    def _init_ui(self) -> None:
        root = QVBoxLayout(self)

        src_box = QGroupBox("CSV Source")
        sf = QVBoxLayout(src_box)
        row = QHBoxLayout()
        self.txt_csv = QLineEdit(self)
        self.btn_browse = QPushButton("Browse...")
        self.btn_browse.clicked.connect(self._browse_csv)  # type: ignore
        self.btn_preview = QPushButton("Refresh preview")
        self.btn_preview.clicked.connect(self._refresh_preview)  # type: ignore
        row.addWidget(self.txt_csv)
        row.addWidget(self.btn_browse)
        row.addWidget(self.btn_preview)
        sf.addLayout(row)
        self._time_hint = QLabel("First CSV column is used as Time. Columns 2+ are available for output mapping.")
        self._time_hint.setStyleSheet("color: #888; font-size: 10px;")
        sf.addWidget(self._time_hint)
        root.addWidget(src_box)

        map_box = QGroupBox("Output Mapping")
        mv = QVBoxLayout(map_box)
        self.tbl_outputs = QTableWidget(0, 3, self)
        self.tbl_outputs.setHorizontalHeaderLabels(["CSV column", "Type", "Target / alias"])
        self.tbl_outputs.horizontalHeader().setSectionResizeMode(0, QHeaderView.Stretch)
        self.tbl_outputs.horizontalHeader().setSectionResizeMode(1, QHeaderView.ResizeToContents)
        self.tbl_outputs.horizontalHeader().setSectionResizeMode(2, QHeaderView.Stretch)
        self.tbl_outputs.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.tbl_outputs.setSelectionMode(QAbstractItemView.SingleSelection)
        self.tbl_outputs.itemDoubleClicked.connect(self._on_output_item_double_clicked)  # type: ignore
        mv.addWidget(self.tbl_outputs)
        btn_row = QHBoxLayout()
        self.btn_add_output = QPushButton("Add output")
        self.btn_remove_output = QPushButton("Remove selected")
        self.btn_suggest_outputs = QPushButton("Suggest from CSV")
        self.btn_add_output.clicked.connect(lambda *_: self._add_output_row())  # type: ignore
        self.btn_remove_output.clicked.connect(self._remove_selected_output)  # type: ignore
        self.btn_suggest_outputs.clicked.connect(self._suggest_outputs_from_csv)  # type: ignore
        btn_row.addWidget(self.btn_add_output)
        btn_row.addWidget(self.btn_remove_output)
        btn_row.addWidget(self.btn_suggest_outputs)
        btn_row.addStretch(1)
        mv.addLayout(btn_row)
        self._map_hint = QLabel(
            f"Loadbank rows command the LoadBank plugin directly; commanded kW is echoed as {self._loadbank_setpoint_alias}."
        )
        self._map_hint.setStyleSheet("color: #888; font-size: 10px;")
        mv.addWidget(self._map_hint)
        root.addWidget(map_box)

        preview_box = QGroupBox("Cycle Profile Preview")
        pv = QVBoxLayout(preview_box)
        if _HAS_CHARTS:
            self._chart = QChart()
            self._chart.setBackgroundBrush(QColor("#1e1e1e"))
            self._chart.legend().setVisible(True)
            self._chart.legend().setLabelColor(QColor("#cccccc"))
            self._chart.setMargins(QMargins(4, 4, 4, 4))
            self._chart_view = QChartView(self._chart)
            self._chart_view.setRenderHint(QPainter.RenderHint.Antialiasing)
            self._chart_view.setMinimumHeight(220)
            pv.addWidget(self._chart_view)
        else:
            self._chart = None
            self._chart_view = None
            lbl = QLabel("(PySide6-Charts not available for plot preview)")
            lbl.setMinimumHeight(60)
            pv.addWidget(lbl)
        self._preview_status = QLabel("")
        pv.addWidget(self._preview_status)
        root.addWidget(preview_box)

        ex = QGroupBox("Execution")
        ef = QFormLayout(ex)
        self.spin_loops = QSpinBox(self)
        self.spin_loops.setRange(1, 100000)
        self.spin_loops.setValue(1)
        self.spin_loops.valueChanged.connect(lambda *_: self._refresh_preview())  # type: ignore
        self.chk_start_with_test = QCheckBox("Start with test")
        ef.addRow("Loops total", self.spin_loops)
        ef.addRow(self.chk_start_with_test)
        root.addWidget(ex)

        btns = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel, parent=self)
        btns.accepted.connect(self._on_accept)  # type: ignore
        btns.rejected.connect(self.reject)  # type: ignore
        root.addWidget(btns)

    # ------------------------------------------------------------------
    # CSV and mapping helpers
    # ------------------------------------------------------------------

    def _resolve_csv_path(self, rel_or_abs: str) -> Optional[Path]:
        p = Path(rel_or_abs.strip())
        if p.is_absolute() and p.exists():
            return p
        cand = self._project_root / p
        if cand.exists():
            return cand
        cand2 = (self._project_root / "configs" / p).resolve()
        if cand2.exists():
            return cand2
        return None

    def _browse_csv(self) -> None:
        start = str(self._project_root / "configs")
        path, _ = QFileDialog.getOpenFileName(self, "Select cycle CSV", start, "CSV (*.csv);;All (*.*)")
        if path:
            try:
                rel = Path(path).resolve().relative_to(self._project_root)
                self.txt_csv.setText(str(rel).replace("\\", "/"))
            except Exception:
                self.txt_csv.setText(path)
            self._suggest_outputs_from_csv()
            self._refresh_preview()

    def _read_csv_data(self) -> Tuple[List[str], List[float], Dict[str, List[float]]]:
        raw = self.txt_csv.text().strip()
        resolved = self._resolve_csv_path(raw)
        if resolved is None or not resolved.exists():
            raise FileNotFoundError(raw)
        text = resolved.read_text(encoding="utf-8-sig", errors="replace")
        reader = csv.DictReader(io.StringIO(text))
        headers = [str(h or "").strip() for h in (reader.fieldnames or [])]
        if not headers:
            raise ValueError("CSV has no header row")
        reader.fieldnames = headers
        col_time = headers[0]
        times: List[float] = []
        columns: Dict[str, List[float]] = {h: [] for h in headers[1:] if h}
        for row in reader:
            try:
                t = float(row.get(col_time, ""))
            except Exception:
                continue
            times.append(t)
            for h in columns.keys():
                try:
                    columns[h].append(float(row.get(h, 0.0) or 0.0))
                except Exception:
                    columns[h].append(0.0)
        self._csv_headers = headers
        self._refresh_csv_column_combos()
        return headers, times, columns

    def _add_output_row(self, mapping: Dict[str, str] | None = None) -> None:
        mapping = dict(mapping or {})
        row = self.tbl_outputs.rowCount()
        self.tbl_outputs.insertRow(row)

        col_combo = QComboBox(self)
        col_combo.setEditable(True)
        self._populate_csv_column_combo(col_combo)
        if mapping.get("csv_column"):
            col_combo.setCurrentText(str(mapping.get("csv_column")))
        self.tbl_outputs.setCellWidget(row, 0, col_combo)

        type_combo = QComboBox(self)
        type_combo.addItems(_OUTPUT_TYPES)
        typ = str(mapping.get("type", "loadbank"))
        type_combo.setCurrentText(typ if typ in _OUTPUT_TYPES else "loadbank")
        type_combo.currentTextChanged.connect(lambda *_args, r=row: self._sync_target_cell(r))  # type: ignore
        self.tbl_outputs.setCellWidget(row, 1, type_combo)

        target = QTableWidgetItem(str(mapping.get("alias", "")))
        self.tbl_outputs.setItem(row, 2, target)
        self._sync_target_cell(row)

    def _populate_csv_column_combo(self, combo: QComboBox) -> None:
        current = combo.currentText()
        combo.blockSignals(True)
        combo.clear()
        for h in self._csv_headers[1:]:
            if h:
                combo.addItem(h)
        if current:
            combo.setCurrentText(current)
        combo.blockSignals(False)

    def _refresh_csv_column_combos(self) -> None:
        for row in range(self.tbl_outputs.rowCount()):
            combo = self.tbl_outputs.cellWidget(row, 0)
            if isinstance(combo, QComboBox):
                self._populate_csv_column_combo(combo)

    def _sync_target_cell(self, row: int) -> None:
        typ = self._row_type(row)
        item = self.tbl_outputs.item(row, 2)
        if item is None:
            item = QTableWidgetItem("")
            self.tbl_outputs.setItem(row, 2, item)
        if typ == "loadbank":
            item.setText(f"LoadBank command (echo: {self._loadbank_setpoint_alias})")
            item.setFlags(Qt.ItemIsSelectable | Qt.ItemIsEnabled)
        else:
            if item.text().startswith("LoadBank command"):
                item.setText("")
            item.setFlags(Qt.ItemIsSelectable | Qt.ItemIsEnabled)

    def _row_type(self, row: int) -> str:
        combo = self.tbl_outputs.cellWidget(row, 1)
        return combo.currentText() if isinstance(combo, QComboBox) else "loadbank"

    def _row_csv_column(self, row: int) -> str:
        combo = self.tbl_outputs.cellWidget(row, 0)
        return combo.currentText().strip() if isinstance(combo, QComboBox) else ""

    def _remove_selected_output(self) -> None:
        rows = sorted({idx.row() for idx in self.tbl_outputs.selectedIndexes()}, reverse=True)
        for row in rows:
            self.tbl_outputs.removeRow(row)
        self._refresh_preview()

    def _on_output_item_double_clicked(self, item: QTableWidgetItem) -> None:
        row = item.row()
        if item.column() != 2 or self._row_type(row) == "loadbank":
            return
        current = item.text().strip()
        dlg = AliasPickerDialog(parent=self, current_alias=current)
        if dlg.exec() == QDialog.Accepted and dlg.selected_alias:
            item.setText(dlg.selected_alias)
            self._refresh_preview()

    def _suggest_outputs_from_csv(self) -> None:
        try:
            headers, _times, _columns = self._read_csv_data()
        except Exception:
            return
        data_cols = [h for h in headers[1:] if h]
        if not data_cols:
            return
        self.tbl_outputs.setRowCount(0)
        for col in data_cols:
            typ = "loadbank" if col.lower() == "load" else "nidaq_do"
            self._add_output_row({"csv_column": col, "type": typ})
        self._refresh_preview()

    def _outputs_from_table(self) -> List[Dict[str, str]]:
        outputs: List[Dict[str, str]] = []
        seen: set[str] = set()
        time_col = self._csv_headers[0] if self._csv_headers else ""
        for row in range(self.tbl_outputs.rowCount()):
            col = self._row_csv_column(row)
            typ = self._row_type(row)
            if not col:
                continue
            if col == time_col:
                raise ValueError(f"CSV column '{col}' is the time column and cannot be mapped as an output")
            if col in seen:
                raise ValueError(f"Duplicate CSV column mapping: {col}")
            seen.add(col)
            out = {"csv_column": col, "type": typ}
            if typ in {"nidaq_do", "nidaq_ao"}:
                item = self.tbl_outputs.item(row, 2)
                alias = item.text().strip() if item is not None else ""
                if not alias:
                    raise ValueError(f"Output '{col}' requires an alias")
                out["alias"] = alias
            outputs.append(out)
        if not outputs:
            raise ValueError("At least one output mapping is required")
        return outputs

    # ------------------------------------------------------------------
    # Preview
    # ------------------------------------------------------------------

    def _refresh_preview(self) -> None:
        self._preview_status.setText("")
        if not self.txt_csv.text().strip():
            self._preview_status.setText("(no CSV path)")
            self._clear_plot()
            return
        try:
            headers, times, columns = self._read_csv_data()
            outputs = self._outputs_from_table()
        except Exception as e:
            self._preview_status.setText(str(e))
            self._clear_plot()
            return
        if not times:
            self._preview_status.setText("No numeric time rows found")
            self._clear_plot()
            return
        missing = [o["csv_column"] for o in outputs if o["csv_column"] not in columns]
        if missing:
            self._preview_status.setText("Missing CSV column(s): " + ", ".join(missing))
            self._clear_plot()
            return
        loops = max(1, self.spin_loops.value())
        try:
            series, total_duration, loop_boundaries = build_expanded_cycle_profiles(times, columns, outputs, loops=loops)
            self._draw_plot(series, total_duration, loop_boundaries)
        except Exception as e:
            self._preview_status.setText(f"Plot error: {e}")
            return
        self._preview_status.setText(
            f"{len(times)} points · {len(outputs)} output(s) · {loops} loop(s) · duration {max(times) - min(times):.1f} s"
        )

    def _clear_plot(self) -> None:
        if self._chart is None:
            return
        self._chart.removeAllSeries()
        for ax in self._chart.axes():
            self._chart.removeAxis(ax)
        self._series_refs.clear()
        self._chart.setTitle("")

    def _style_axis(self, axis: QValueAxis, label: str) -> None:
        axis.setTitleText(label)
        axis.setTitleBrush(QColor("#cccccc"))
        axis.setLabelsBrush(QColor("#aaaaaa"))
        axis.setLabelsFont(QFont("Segoe UI", 7))
        axis.setGridLineColor(QColor("#333333"))
        axis.setLinePenColor(QColor("#444444"))

    def _draw_plot(self, series: List[CyclePlotSeries], total_duration: float, loop_boundaries: List[float]) -> None:
        if self._chart is None:
            return
        self._chart.removeAllSeries()
        for ax in self._chart.axes():
            self._chart.removeAxis(ax)
        self._series_refs.clear()
        if not series:
            return

        x_axis = QValueAxis()
        self._style_axis(x_axis, "Time (s)")
        x_axis.setRange(0.0, max(1.0, total_duration))
        self._chart.addAxis(x_axis, Qt.AlignmentFlag.AlignBottom)

        y_left = QValueAxis()
        self._style_axis(y_left, "Analog / load")
        left_vals = [v for s in series if s.axis != "right" for v in s.values]
        left_max = max(left_vals or [1.0])
        y_left.setRange(0.0, max(1.0, left_max * 1.1))
        self._chart.addAxis(y_left, Qt.AlignmentFlag.AlignLeft)

        y_right = None
        right_vals = [v for s in series if s.axis == "right" for v in s.values]
        if right_vals:
            y_right = QValueAxis()
            self._style_axis(y_right, "Digital")
            y_right.setRange(0.0, max(1.1, max(right_vals) * 1.1))
            self._chart.addAxis(y_right, Qt.AlignmentFlag.AlignRight)

        for spec in series:
            qseries = QLineSeries()
            qseries.setName(spec.name)
            qseries.setPen(QPen(QColor(spec.color), 1.8))
            for t, v in zip(spec.times, spec.values):
                qseries.append(QPointF(float(t), float(v)))
            self._series_refs.append(qseries)
            self._chart.addSeries(qseries)
            qseries.attachAxis(x_axis)
            qseries.attachAxis(y_right if spec.axis == "right" and y_right is not None else y_left)

        if loop_boundaries:
            top = max(max(left_vals or [1.0]), 1.0)
            for x in loop_boundaries:
                vline = QLineSeries()
                vline.setName("")
                vline.setPen(QPen(QColor("#555555"), 0.8, Qt.PenStyle.DashLine))
                vline.append(QPointF(float(x), 0.0))
                vline.append(QPointF(float(x), float(top)))
                self._series_refs.append(vline)
                self._chart.addSeries(vline)
                vline.attachAxis(x_axis)
                vline.attachAxis(y_left)

    # ------------------------------------------------------------------
    # Config load/save
    # ------------------------------------------------------------------

    def _read_yaml(self, path: Path) -> Dict[str, Any]:
        try:
            import yaml  # type: ignore

            if not path.exists():
                return {}
            return yaml.safe_load(path.read_text(encoding="utf-8")) or {}
        except Exception:
            return {}

    def _load(self, defer_preview: bool = False) -> None:
        self._cfg = self._read_yaml(self._cfg_path)
        c = self._cfg

        src = (c.get("source") or {}) if isinstance(c.get("source"), dict) else {}
        self.txt_csv.setText(str(src.get("csv_path", "") or ""))
        cols = src.get("columns") or {}

        ex = (c.get("execution") or {}) if isinstance(c.get("execution"), dict) else {}
        try:
            self.spin_loops.setValue(int(ex.get("loops_total", 1)))
        except Exception:
            self.spin_loops.setValue(1)
        self.chk_start_with_test.setChecked(bool(ex.get("start_with_test", False)))

        try:
            self._read_csv_data()
        except Exception:
            pass
        outputs = c.get("outputs") if isinstance(c.get("outputs"), list) else []
        if not outputs:
            legacy_load = str(cols.get("load", "Load")) if isinstance(cols, dict) else "Load"
            outputs = [{"csv_column": legacy_load, "type": "loadbank"}]
        self.tbl_outputs.setRowCount(0)
        for out in outputs:
            if isinstance(out, dict):
                self._add_output_row({k: str(v) for k, v in out.items()})

        if defer_preview:
            QTimer.singleShot(100, self._refresh_preview)
        else:
            self._refresh_preview()

    def _build_doc(self) -> Dict[str, Any]:
        outputs = self._outputs_from_table()
        return {
            "source": {
                "csv_path": self.txt_csv.text().strip() or "configs/cycles/demo.csv",
            },
            "execution": {
                "loops_total": int(self.spin_loops.value()),
                "start_with_test": self.chk_start_with_test.isChecked(),
            },
            "outputs": outputs,
        }

    def _save_and_reload(self) -> bool:
        try:
            doc = self._build_doc()
        except Exception as e:
            QMessageBox.warning(self, "Invalid Cycle Mapping", str(e))
            return False
        csv_path = (doc.get("source") or {}).get("csv_path") if isinstance(doc.get("source"), dict) else None
        if csv_path:
            resolved = self._resolve_csv_path(str(csv_path))
            if resolved is None or not resolved.exists():
                QMessageBox.warning(
                    self,
                    "CSV not found",
                    "The CSV path does not resolve to an existing file. The YAML will still be saved.",
                )
        try:
            import yaml  # type: ignore

            self._cfg_path.write_text(yaml.safe_dump(doc, sort_keys=False), encoding="utf-8")
            self._cfg = dict(doc)
        except Exception as e:
            QMessageBox.critical(self, "Write Error", f"Failed to save cycle.yaml: {e}")
            return False

        try:
            from src.core.ipc.bus import create_ui_control_push  # type: ignore

            ctrl = create_ui_control_push()
            if ctrl is not None:
                msg = json.dumps({"type": "reload_plugin", "plugin": "Cycle"}).encode("utf-8")
                ctrl["control_push"].send(msg)
        except Exception:
            pass
        return True

    def _on_accept(self) -> None:
        if not self._save_and_reload():
            return
        self.accept()

    def _loadbank_setpoint_alias_from_config(self) -> str:
        try:
            import yaml  # type: ignore

            p = self._project_root / "configs" / "loadbank.yaml"
            data = yaml.safe_load(p.read_text(encoding="utf-8")) or {}
            exposes = data.get("expose_channels") or {}
            return str(exposes.get("setpoint_alias", "lPO_LdbStp"))
        except Exception:
            return "lPO_LdbStp"
