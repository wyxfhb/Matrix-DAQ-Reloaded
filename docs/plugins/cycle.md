<!-- Author: T. Onkst | Date: 05222026 -->

## Cycle Plugin Specification

### Purpose
Execute a user-defined, time-based output schedule from a CSV file. A cycle can command one or more outputs from the same CSV, including LoadBank setpoints, NI digital outputs, and NI analog outputs. There is no interpolation: output values are held until the next timestamp (step behavior).

### CSV Schema
- File format: CSV
- Column 1 is always time, regardless of the header name (`Time`, `Seconds`, etc.)
- Columns 2+ are output columns that can be mapped in `cycle.yaml` or the Configure Cycle dialog
- Semantics:
  - Time is in seconds and should be monotonically non-decreasing
  - Output values are applied at the specified time and held until the next row
  - LoadBank values are kW
  - NI digital output values are rounded to 0/1
  - NI analog output values are sent as numeric values to the selected alias
  - Any desired dwell time should be included directly in the CSV rows

### State Machine
The cycle plugin maintains an internal state:

| State | Description |
|-------|-------------|
| `idle` | Not started; waiting for play command |
| `running` | Actively advancing through the schedule; mapped outputs are applied |
| `paused` | Timer frozen; last commanded output values are held |
| `complete` | All loops finished; last commanded output values are held; Play restarts from beginning |

### Runtime Controls
All controls are available via the Cycle Control section in the LoadBank operator panel and routed via IPC to the orchestrator:

- **Play**: start from idle, resume from paused, or restart from complete
- **Pause**: freeze timer at current position; outputs hold last commanded values
- **Seek**: jump to a specific time (only when paused)
- **Loops**: set total loop count at runtime
- **Start with Test**: when enabled, pressing Record starts the cycle and recording simultaneously. If a LoadBank output is mapped, LoadBank Matrix control must be active first.
- **`iCycle_Play`**: a calculated boolean telemetry channel can request Play on a rising edge. It only starts the cycle from `idle` or `complete`; it does not override `paused`.

### Output Mapping
Mappings are stored in `configs/cycle.yaml` under `outputs`.

| Type | Target | Notes |
|------|--------|-------|
| `loadbank` | LoadBank plugin | Commands load setpoint in kW. No alias is required. The commanded value is echoed through the configured LoadBank setpoint telemetry, typically `lPO_LdbStp`. |
| `nidaq_do` | NI DAQ digital output alias | Requires an `alias`. CSV values are rounded and written as 0 or 1. |
| `nidaq_ao` | NI DAQ analog output alias | Requires an `alias`. CSV values are written as analog output values. |

Change detection is applied per output target, so unchanged values are not written every orchestrator tick.

### Integration with LoadBank and NI DAQ
- If a cycle includes a `loadbank` output, the orchestrator enables Master Load when the cycle plays
- LoadBank setpoint commands are sent only when the mapped load value changes
- DO/AO commands are sent through the NI DAQ plugin only when the mapped value changes
- On pause: last commanded output values are held; Master Load stays on when a LoadBank output is active
- On complete/stop: last commanded output values are held (no auto-zero); operator uses Emergency Stop / Zero Load to drop load manually when needed
- Rate limiting and step decomposition handled by LoadBank per model map

### Execution Model
- At each orchestrator tick:
  - `simulate_step()` computes current position, mapped output values, loop number, and progress
  - `CycleOutputDriver` applies changed mapped outputs to their hardware targets
- Loop boundary: when elapsed time exceeds `loop_len * loops_total`, state transitions to `complete`
- Multi-loop: elapsed time wraps via modulo for `loops_total > 1`

### Telemetry Channels
Published every tick by `simulate_step()`:

| Channel | Unit | Description |
|---------|------|-------------|
| `Cycle/state` | — | State code: 0=idle, 1=running, 2=paused, 3=complete |
| `Cycle/position_s` | s | Current position within the active loop |
| `Cycle/setpoint_kw` | kW | Current load setpoint from schedule, kept for LoadBank compatibility |
| `Cycle/loop_current` | — | Current loop number (1-based) |
| `Cycle/loop_total` | — | Total configured loops |
| `Cycle/progress_pct` | % | Overall progress across all loops |
| `Cycle/schedule_len_s` | s | Duration of one loop |
| `Cycle/elapsed_s` | s | Elapsed cycle time |
| `Cycle/output/<label>` | varies | Current value for each mapped output. DO outputs use `bool`; LoadBank outputs use `kW`. |

### Configuration (YAML)
File: `configs/cycle.yaml`

```yaml
source:
  csv_path: configs/cycles/demo.csv
execution:
  loops_total: 1
  start_with_test: false
outputs:
  - csv_column: Load
    type: loadbank
  - csv_column: DigOut
    type: nidaq_do
    alias: xIgnition
  - csv_column: Throttle
    type: nidaq_ao
    alias: aThrottleCmd
```

Existing configs that still contain `source.columns.time` are tolerated, but the value is ignored. The first CSV column is always the time source. If no `outputs` block exists, the plugin falls back to the legacy Load column as a LoadBank output.

### UI

#### Configure Dialog (right-click Cycle tile -> Configure)
- **CSV Source**: browse/enter CSV path; first CSV column is shown as the time source by contract
- **Output Mapping**: map CSV columns 2+ to `loadbank`, `nidaq_do`, or `nidaq_ao`; DO/AO rows use the alias picker for target selection
- **Preview**: embedded QtCharts multi-series step plot with a legend and a digital axis when needed
- **Execution**: loops total and start with test checkbox

#### Cycle Control Section (in LoadBank operator panel)
- **Start with Test** checkbox
- **State/Position/Setpoint/Loop** labels updated from telemetry
- **Progress bar** showing overall completion percentage
- **CycleChartWidget**: lightweight QPainter multi-series step-line chart with legend, axis labels, and red vertical position marker
- **Play/Pause** buttons
- **Seek** spinner + Go button (active when paused)
- **Loops** spinner

The `CycleChartWidget` (`src/ui/widgets/cycle_chart.py`) is imported with a `try/except` guard — if the file is missing on a workstation, the chart area is simply omitted and the rest of the panel functions normally.

### Error Handling
- CSV parse/validation errors -> status label in config dialog
- Runtime validation fails if an output mapping points at CSV column 1/time
- LoadBank comms loss: system policy via calculated-channel estop logic
- Missing `cycle_chart.py` on workstation: graceful degradation, panel loads without chart

### Outputs and Metadata
- Telemetry channels are recorded at core tick rate (see table above)
- Boundary and loop events logged to console
