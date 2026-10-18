"""Bounded serial acquisition based on the recovered driver_test.py.

Importing this module does not open a device. Hardware operation has not been
verified in this curated copy.
"""

import time

import numpy as np
import serial
from serial.tools import list_ports

from measurements import validate_spectrum


class SpectrometerError(Exception):
    """A device, protocol, cancellation or acquisition-timeout error."""


def find_spectrometer_port():
    """Use the original Arduino description hint; reject ambiguous matches."""
    matches = [
        port.device for port in list_ports.comports()
        if "arduino" in (port.description or "").casefold()
    ]
    if len(matches) > 1:
        raise SpectrometerError("Several Arduino ports found; select one with --port.")
    return matches[0] if matches else None


def parse_serial_line(raw):
    """Return a numeric pair, the 'end' marker, or None for device chatter.

    The recovered driver accepts x=d,<wavelength>,<label>,<intensity> rows
    and requires x=e to finish a measurement. The third field is retained as
    an opaque device label because no firmware/specification was recovered.
    """
    try:
        line = raw.decode("ascii").strip() if isinstance(raw, bytes) else raw.strip()
    except UnicodeDecodeError as exc:
        raise SpectrometerError("Device sent non-ASCII measurement data.") from exc
    if line == "x=e":
        return "end"
    if not line.startswith("x=d"):
        return None
    fields = line.split(",")
    if len(fields) != 4 or fields[0] != "x=d" or not fields[2].strip():
        raise SpectrometerError("Malformed device measurement row.")
    try:
        pair = (float(fields[1]), float(fields[3]))
    except ValueError as exc:
        raise SpectrometerError("Device measurement contains a nonnumeric value.") from exc
    if not all(np.isfinite(value) for value in pair):
        raise SpectrometerError("Device measurement contains a nonfinite value.")
    return pair


def read_spectrum(connection, *, timeout=10.0, cancelled=None, clock=time.monotonic,
                  max_points=4096):
    """Read a complete spectrum with a deadline and bounded row length.

    The caller owns the connection and must set its read timeout to at most
    0.2 seconds so cancellation and the deadline remain responsive.
    """
    if not np.isfinite(timeout) or timeout <= 0:
        raise ValueError("Acquisition timeout must be a positive finite number.")
    deadline = clock() + timeout
    x_data, y_data = [], []
    pending = b""
    while clock() < deadline:
        if cancelled is not None and cancelled():
            raise SpectrometerError("Acquisition cancelled.")
        chunk = connection.read_until(expected=b"\n", size=256)
        if not chunk:
            continue
        pending += chunk
        if len(pending) > 256 or (len(pending) == 256 and not pending.endswith(b"\n")):
            raise SpectrometerError("Device row exceeds the 256-byte limit.")
        if not pending.endswith(b"\n"):
            continue
        raw, pending = pending, b""
        parsed = parse_serial_line(raw)
        if parsed == "end":
            try:
                return validate_spectrum(x_data, y_data)
            except ValueError as exc:
                raise SpectrometerError(str(exc)) from exc
        if parsed is not None:
            if len(x_data) >= max_points:
                raise SpectrometerError("Device measurement exceeds the point limit.")
            x_data.append(parsed[0])
            y_data.append(parsed[1])
    raise SpectrometerError("Measurement timed out before the x=e end marker.")


def activate_and_read_spectrometer(port=None, *, timeout=10.0, cancelled=None,
                                   serial_factory=None):
    """Trigger a measurement and always close the connection, including errors."""
    if not np.isfinite(timeout) or timeout <= 0 or timeout > 60:
        raise ValueError("Acquisition timeout must be between 0 and 60 seconds.")
    try:
        selected_port = port or find_spectrometer_port()
        if not selected_port:
            raise SpectrometerError("No Arduino device found. Use --port or offline demo mode.")
        factory = serial_factory or serial.Serial
        connection = factory(selected_port, 115200, timeout=min(0.2, timeout), write_timeout=1)
        try:
            if cancelled is not None and cancelled():
                raise SpectrometerError("Acquisition cancelled.")
            if connection.write(b"m") != 1:
                raise SpectrometerError("Could not send the measurement command.")
            return read_spectrum(connection, timeout=timeout, cancelled=cancelled)
        finally:
            connection.close()
    except (serial.SerialException, OSError) as exc:
        raise SpectrometerError("Could not communicate with the serial device: " + str(exc)) from exc
