"""Measurement files, comparison math and clearly synthetic offline samples."""

from pathlib import Path

import numpy as np


def validate_spectrum(wavelengths, intensities):
    x = np.asarray(wavelengths, dtype=float)
    y = np.asarray(intensities, dtype=float)
    if x.ndim != 1 or y.ndim != 1 or x.size != y.size or x.size < 2:
        raise ValueError("A spectrum needs at least two paired wavelength/intensity values.")
    if not np.all(np.isfinite(x)) or not np.all(np.isfinite(y)):
        raise ValueError("Measurement values must be finite numbers.")
    return x, y


def validate_name(name):
    name = name.strip()
    if not name or "\n" in name or "\r" in name:
        raise ValueError("Enter a nonempty measurement name on one line.")
    return name


def parse_measurements(text):
    """Read the original named-block text format without partial imports."""
    measurements = []
    lines = text.lstrip("\ufeff").splitlines()
    blocks, block = [], []
    for line in lines + [""]:
        if line.strip():
            block.append(line)
        elif block:
            blocks.append(block)
            block = []
    for block in blocks:
        name = validate_name(block[0])
        x, y = [], []
        for line in block[1:]:
            fields = line.split(",")
            if len(fields) != 2:
                raise ValueError("Each measurement row must contain wavelength, intensity.")
            try:
                x.append(float(fields[0]))
                y.append(float(fields[1]))
            except ValueError as exc:
                raise ValueError("Measurement rows must contain numeric values.") from exc
        x_array, y_array = validate_spectrum(x, y)
        measurements.append((name, x_array, y_array))
    if not measurements:
        raise ValueError("No measurements found in the file.")
    return measurements


def load_measurements(path):
    raw = Path(path).read_bytes()
    try:
        text = raw.decode("utf-8-sig")
    except UnicodeDecodeError:
        # The original Bulgarian Windows app used the system text encoding.
        text = raw.decode("cp1251")
    return parse_measurements(text)


def format_measurements(measurements):
    blocks = []
    for name, x, y in measurements:
        name = validate_name(name)
        x, y = validate_spectrum(x, y)
        rows = [name] + [f"{xi:.17g}, {yi:.17g}" for xi, yi in zip(x, y)]
        blocks.append("\n".join(rows))
    if not blocks:
        raise ValueError("Select at least one measurement to save.")
    return "\n\n".join(blocks) + "\n"


def pearson_correlation(first, second):
    """Compare aligned spectra; reject undefined constant or mismatched data."""
    x1, y1 = validate_spectrum(*first)
    x2, y2 = validate_spectrum(*second)
    if x1.shape != x2.shape or not np.allclose(x1, x2, rtol=0, atol=1e-9):
        raise ValueError("Comparison requires matching wavelength grids; resample externally first.")
    # Scale first to keep centering/dot products finite for large input values.
    scale1, scale2 = np.max(np.abs(y1)), np.max(np.abs(y2))
    scaled1 = y1 / scale1 if scale1 else y1
    scaled2 = y2 / scale2 if scale2 else y2
    centered1, centered2 = scaled1 - np.mean(scaled1), scaled2 - np.mean(scaled2)
    norm1, norm2 = np.linalg.norm(centered1), np.linalg.norm(centered2)
    if norm1 == 0 or norm2 == 0:
        raise ValueError("Correlation is undefined for a constant spectrum.")
    value = np.dot(centered1 / norm1, centered2 / norm2)
    return float(np.clip(value, -1.0, 1.0))


def demo_measurements():
    """Two deterministic artificial curves, not captured or calibrated readings."""
    x = np.linspace(400.0, 750.0, 176)
    first = 20 + 90 * np.exp(-((x - 520) / 27) ** 2) + 55 * np.exp(-((x - 635) / 40) ** 2)
    second = 22 + 87 * np.exp(-((x - 526) / 29) ** 2) + 47 * np.exp(-((x - 637) / 42) ** 2)
    return [("Synthetic reference", x.copy(), first), ("Synthetic comparison", x.copy(), second)]
