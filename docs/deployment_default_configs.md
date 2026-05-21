<!-- Author: T. Onkst | Date: 05052026 -->

# Default configuration package (distributable)

This document describes which files under `configs/` should ship with a default install, and why. It complements plugin-specific docs under `docs/plugins/`.

## Goals of the default bundle

1. **Core process stays alive** and publishes telemetry on the expected schedule.
2. **Launch UI** can list plugins and displays from a single registry file.
3. **Operator workflow** matches expectations: console link status, plugin tiles, lock/recording, and optional alarms.
4. **Paths are portable** (relative to the project/install root), so customer machines are not hard-coded.

---

## Why `core.yaml` must be present

If `configs/core.yaml` is missing, `load_yaml_config` returns an empty mapping and the orchestrator treats **`run_mode` as `demo`**.

- In **`demo`** mode, the main loop runs for a **finite** number of ticks (`demo_ticks`, default 50), then the core run ends and the subprocess exits.
- In **`continuous`** mode (or any non-`demo` `run_mode`), the main loop runs until shutdown.

After the core exits, the UI no longer receives fresh **`telemetry`** messages on the IPC bus, so the console considers the link **disconnected**. Plugin tiles are then shown as **grey** with the subtitle **“Unknown”** regardless of individual plugin YAML edits, because that state is driven by **telemetry liveness**, not by per-plugin config files.

**Shipping default:** include `configs/core.yaml` with at least:

- `run_mode: continuous` (recommended for production / lab installs)
- `tick_interval_s` aligned with your desired default cadence
- `demo_ticks` only matters when `run_mode` is `demo`

See `src/core/orchestrator.py` (`run_mode`, `demo_ticks`) and `src/ui/widgets/console.py` (`_refresh_status`, `_conn_latched`, `_last_rx_ts`).

---

## Tier 1 — Shell and launcher (ship always)

| Path | Role |
|------|------|
| `configs/core.yaml` | Core loop mode and timing; avoids accidental demo exit. |
| `configs/plugins.yaml` | Written/read by the launch dialog: `selected_plugins`, `selected_displays`, `data_root`, `test_cell`, `data_mode`, `imported_paths`. If missing, the core may treat **all** registered plugins as enabled (see orchestrator log: no `selected_plugins` in `plugins.yaml`). |
| `configs/app_registry.yaml` | Launch UI: `available_plugins`, `available_displays`. |

---

## Tier 2 — Plugin YAML (one file per registered plugin)

The orchestrator registers one config filename per plugin (`PluginSpec.config_name` in `src/core/orchestrator.py`). Each plugin loads via `BasePlugin.load_config()` → `load_yaml_config`; **missing files become `{}`**, so the core can still start.

However, the console’s **“Invalid config”** path (when telemetry does not expose `…/health_ok` or `…/conn_ok` for that plugin) uses **`_plugin_config_ok`**, which requires the mapped YAML file to **exist and be a non-empty mapping**. For a distributable that shows **red until the operator configures** and **green when valid**, ship **minimal stub** YAMLs (for example `enabled: false` where supported, or the smallest structure that passes each plugin’s `validate()` in sim/offline mode—tune per plugin as needed).

| Plugin ID | Config file |
|-----------|----------------|
| NI_DAQ | `ni_daq.yaml` |
| CAN | `can.yaml` |
| CCP | `ccp.yaml` |
| Calculated_Channels | `calculated_channels.yaml` |
| Cycle | `cycle.yaml` |
| LoadBank | `loadbank.yaml` |
| Modbus | `modbus.yaml` |
| Statistics | `statistics.yaml` |
| Vaisala | `vaisala.yaml` |
| Omega | `omega.yaml` |
| EngineTest | `engine_test.yaml` |
| Channel_Manager | `channel_manager.yaml` |

**Channel manager:** If `channel_manager.yaml` is missing or empty, `_apply_channel_manager_runtime` does **not** construct an `AlarmEngine` (“alarms disabled”). For a normal recorder install, ship a minimal file (for example empty `channels: []` plus defaults for `recording_rate_hz` and `storage` if you rely on those).

---

## Tier 3 — JSON and schema companions

| Path | Role |
|------|------|
| `configs/standard_channels.json` | NI DAQ alias picker (`src/ui/widgets/standard_channels.py`, `nidaq_alias_picker.py`). |
| `configs/scale_library.json` | NI scaling editor presets (`src/ui/widgets/scale_library.py`). |
| `configs/schemas/modbus.schema.json` | Modbus plugin optional schema validation path (`ModbusPlugin` / `configs_dir/schemas/`). |

---

## Tier 4 — Referenced assets (ship if your default YAML points at them)

- **`configs/cycles/*.csv`** — Cycle plugin `source.csv_path` must resolve on disk (see `docs/plugins/cycle.md` and `cycle.yaml`).
- **`configs/loadbanks/*.yaml`** — Load bank device map files referenced from `loadbank.yaml`. Prefer **relative** paths (for example `configs/loadbanks/Acme-LB100.yaml`) so the package is not tied to a developer’s absolute path.

---

## Tier 5 — Optional / generated

| Path | Notes |
|------|--------|
| `configs/test_monitor_display.yaml` | Main Test Monitor layout (`src/ui/widgets/test_monitor_display.py`). Include if you ship that display by default. |
| `configs/ni_daq.generated.yaml` | Optional inventory output from discovery tooling; not required for first boot. |
| `configs/alias_library.yaml` | Not loaded by current `src/` alias picker (picker uses `standard_channels.json`). Safe to omit from runtime bundle unless you keep it for documentation or legacy workflows. |

---

## Recording and config snapshots

When recording starts, the storage layer snapshots **`configs/*.yaml`** from the configs directory into the run folder (see `src/core/storage/sqlite_writer.py` and `parquet_writer.py`). Shipping a **consistent** set of root-level YAMLs improves supportability of captured runs.

---

## Quick checklist for packagers

- [ ] `core.yaml` with `run_mode: continuous` (or deliberate `demo` for short demos only)
- [ ] `plugins.yaml` template with sensible default `selected_plugins` / `data_root`
- [ ] `app_registry.yaml`
- [ ] Stub or minimal **non-empty** YAML for each plugin in Tier 2 (including `channel_manager.yaml`, `engine_test.yaml`)
- [ ] `standard_channels.json`, `scale_library.json`, `schemas/modbus.schema.json` if those UIs/plugins are enabled
- [ ] Any CSV / loadbank YAML referenced by default `cycle.yaml` / `loadbank.yaml`, using **relative** paths

---

## Related documentation

- `docs/flows.md` — Session setup and console behavior at a high level
- `docs/plugins/*.md` — Per-plugin configuration semantics
