# Spectrometer Desktop

Open saved measurements, overlay spectra, compare aligned curves and export data or plots in a **Python/PyQt5 desktop app**.

This personal application demo shows scientific desktop UI, measurement-file validation, numerical comparison and background serial-workflow code. It starts with two labelled synthetic curves, so the full file/plot workflow can be explored without an instrument.

![Offline demo with two synthetic spectra](docs/demo.png)

## Explore the demo

After [setup](#setup), run:

```powershell
.\.venv\Scripts\python.exe Spektrometar.py --demo
```

Running without arguments also selects this offline mode.

1. Toggle curves with their checkboxes and use the Matplotlib toolbar to pan or zoom.
2. Right-click a measurement to rename, delete or compare it. **Measurements → Compare measurements** also opens the comparison workflow.
3. Save checked curves through **File → Save measurements**, then reopen the text file through **File → Open measurements**.
4. Use **File → Export plot** to save PNG, JPG or PDF output.
5. Choose **Load synthetic demo** to add another artificial pair.

The comparison reports Pearson correlation between intensity arrays on matching wavelength grids. Duplicate imported names receive numbered suffixes. Invalid files are parsed before records are added, and constant curves or incompatible grids produce a comparison error.

The implementation separates GUI controls, file/math operations and a serial worker. Acquisition uses a `QThread` and signals so serial reading can proceed separately from the GUI event loop; the offline tests exercise that behavior with fake acquisition.

## Setup

Use **Python 3.12**. Dependencies are pinned to the Windows verification environment. Run from the repository root.

Windows PowerShell:

```powershell
py -3.12 -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
.\.venv\Scripts\python.exe Spektrometar.py --demo
```

Linux/macOS command equivalents:

```bash
python3.12 -m venv .venv
.venv/bin/python -m pip install -r requirements.txt
.venv/bin/python Spektrometar.py --demo
```

Dependency installation requires internet access. The offline demo has no network or hardware dependency. Linux/macOS desktop behavior has not been verified.

## Measurement files

Each block begins with a one-line name, followed by at least two finite `wavelength, intensity` pairs. A blank line separates blocks:

```text
Example A
400, 10
402, 12

Example B
400, 9
402, 13
```

Exports use UTF-8; imports also accept legacy Bulgarian Windows CP1251 files. Measurements stay in memory until explicitly exported. Measurement data is not written beside the source automatically, and the app can be launched from another working directory. No personal measurement files are bundled.

## Optional serial acquisition

The serial workflow is implemented and tested with fake connections. **Physical hardware has not been tested in this curated version.** Enable hardware mode explicitly:

```powershell
.\.venv\Scripts\python.exe Spektrometar.py --hardware --port COM3 --timeout 10
```

Select the actual device port; `/dev/ttyUSB0` is one possible Linux example. Without `--port`, discovery uses the recovered Arduino-description heuristic and rejects ambiguous matches. Obtain operating-system drivers from the device/vendor; none are bundled.

The recovered protocol uses 115200 baud, writes the byte `m`, then expects ASCII rows such as:

```text
x=d,400.0,y=v,123.4
x=d,402.0,y=v,127.8
x=e
```

The third field is an opaque device label. The reader handles fragmented rows, ignores unrelated chatter, caps rows at 256 bytes and measurements at 4096 points, and accepts a measurement only after `x=e`.

`--timeout` sets the serial-reading deadline: **greater than 0 and at most 60 seconds**, default 10. Individual reads wait at most 0.2 seconds and the command write has a one-second timeout. Port discovery/opening occurs before the read deadline and depends on the OS/device. Closing during acquisition requests cancellation and defers window closure until the worker finishes.

## Tests and verified scope

```powershell
.\.venv\Scripts\python.exe -m unittest discover -s tests -v
```

**27 tests passed on Windows on 20 October 2026**, using Python 3.12.4, NumPy 2.5.4, Matplotlib 3.11.2, PyQt5 5.15.11 and pyserial 3.5. This audit reran the existing suite with network access blocked. Serial tests use fake devices and GUI tests use Qt's offscreen platform.

The suite covers:

- Synthetic samples, text/encoding round trips and malformed-file rejection.
- Known correlation values, constant/unaligned inputs and large finite values.
- Fragmented serial rows, deadlines, cancellation, disconnects and connection cleanup.
- Demo startup without opening serial, GUI responsiveness during fake acquisition, duplicate names, save/reload and PNG plot export.

The preview shows the synthetic demo. Hardware compatibility, calibration and physical measurement accuracy are unverified; no firmware, device specification or calibration data is bundled. Intensity is in arbitrary units. Correlation does not identify materials, and automatic resampling, calibration and continuous acquisition are outside this example. Offscreen checks do not establish native desktop behavior on every OS.

## Code and provenance

| File | Responsibility |
|---|---|
| `Spektrometar.py` | PyQt5 interface, plots and acquisition worker lifecycle. |
| `measurements.py` | Named text format, validation, comparison and synthetic samples. |
| `spectrometer_driver.py` | Device discovery, protocol parsing and serial reading. |
| `tests/` | Offline unit and GUI regression tests. |

This repository continues a recovered personal application and retains much of its GUI workflow. See [PROVENANCE.md](PROVENANCE.md) for the source history and publication scope. Dependencies retain their own licenses; no new project-code license has been assigned.
