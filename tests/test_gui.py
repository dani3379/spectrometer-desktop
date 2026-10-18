"""Offscreen UI regressions. All serial acquisition is replaced with fakes."""

import os
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import tempfile
import threading
import time
import unittest
from pathlib import Path
from unittest.mock import patch

from PyQt5.QtCore import QTimer
from PyQt5.QtWidgets import QApplication

from Spektrometar import SpectrometerApp
from measurements import demo_measurements, load_measurements
from spectrometer_driver import SpectrometerError


class GuiTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])
        cls.app.setQuitOnLastWindowClosed(False)

    def setUp(self):
        self.window = None

    def tearDown(self):
        if self.window is not None:
            if self.window.worker is not None:
                self.window.worker.requestInterruption()
                self.until(lambda: self.window.worker is None)
            self.window.close()
            self.window.deleteLater()
            self.app.processEvents()

    def until(self, predicate, timeout=3):
        deadline = time.monotonic() + timeout
        while not predicate() and time.monotonic() < deadline:
            self.app.processEvents()
            time.sleep(0.005)
        self.app.processEvents()
        self.assertTrue(predicate(), "GUI operation did not finish before the test deadline")

    def test_demo_starts_without_opening_serial(self):
        with patch("spectrometer_driver.serial.Serial") as serial_open:
            self.window = SpectrometerApp()
            self.window.show()
            self.app.processEvents()
            self.assertEqual(len(self.window.measurements), 2)
            self.assertEqual(len(self.window.canvas.ax.lines), 2)
            serial_open.assert_not_called()

    def test_add_delete_clear_and_duplicate_names_keep_lists_aligned(self):
        self.window = SpectrometerApp()
        self.window.load_demo()
        self.assertEqual(len(set(self.window.file_names)), 4)
        second_checkbox = list(self.window.checkbox_labels)[1]
        self.window.delete_checkbox(second_checkbox)
        self.assertEqual(self.window.checkbox_layout.count(), 3)
        self.assertEqual(list(self.window.checkbox_labels.values()), self.window.file_names)
        self.window.clear_all_data()
        self.assertEqual(self.window.checkbox_layout.count(), 0)
        self.assertEqual(self.window.measurements, [])
        self.window.load_demo()
        self.assertEqual(len(self.window.measurements), 2)

    def test_rename_rejects_duplicate_name_and_keeps_color(self):
        self.window = SpectrometerApp()
        checkbox = next(iter(self.window.checkbox_labels))
        color = self.window.measurement_colors[checkbox.text()]
        with patch("Spektrometar.QInputDialog.getText", return_value=("Renamed sample", True)):
            self.window.rename_checkbox(checkbox)
        self.assertEqual(self.window.file_names[0], "Renamed sample")
        self.assertEqual(self.window.measurement_colors["Renamed sample"], color)
        with patch("Spektrometar.QInputDialog.getText", return_value=(self.window.file_names[1], True)), \
                patch("Spektrometar.QMessageBox.warning") as warning:
            self.window.rename_checkbox(checkbox)
        warning.assert_called_once()
        self.assertEqual(self.window.file_names[0], "Renamed sample")

    def test_save_reload_export_plot_and_invalid_import_is_atomic(self):
        self.window = SpectrometerApp()
        with tempfile.TemporaryDirectory() as folder:
            target = Path(folder) / "measurements.txt"
            with patch("Spektrometar.QFileDialog.getSaveFileName", return_value=(str(target), "")):
                self.window.save_data()
            self.assertEqual(len(load_measurements(target)), 2)
            self.window.clear_all_data()
            with patch("Spektrometar.QFileDialog.getOpenFileName", return_value=(str(target), "")):
                self.window.open_data()
            self.assertEqual(len(self.window.measurements), 2)
            target.write_text("Valid\n1,2\n2,3\n\nInvalid\n1,2\n", encoding="utf-8")
            with patch("Spektrometar.QFileDialog.getOpenFileName", return_value=(str(target), "")), \
                    patch("Spektrometar.QMessageBox.warning") as warning:
                self.window.open_data()
            self.assertEqual(len(self.window.measurements), 2)
            warning.assert_called_once()
            plot = Path(folder) / "plot.png"
            with patch("Spektrometar.QFileDialog.getSaveFileName", return_value=(str(plot), "")):
                self.window.save_image()
            self.assertGreater(plot.stat().st_size, 1000)

    def test_acquisition_runs_in_worker_and_gui_remains_responsive(self):
        self.window = SpectrometerApp(demo=False, port="FAKE")
        entered, release = threading.Event(), threading.Event()
        observed_threads = []

        def acquire(*args, **kwargs):
            observed_threads.append(threading.current_thread())
            entered.set()
            release.wait(2)
            return demo_measurements()[0][1:]

        ticks = []
        with patch("Spektrometar.activate_and_read_spectrometer", side_effect=acquire), \
                patch("Spektrometar.QInputDialog.getText", return_value=("Mock acquisition", True)):
            try:
                self.window.acquire_data()
                self.until(entered.is_set)
                QTimer.singleShot(0, lambda: ticks.append(True))
                self.until(lambda: bool(ticks))
                self.assertFalse(self.window.acquire_button.isEnabled())
                self.assertEqual(self.window.measurements, [])
                self.assertIsNot(observed_threads[0], threading.current_thread())
            finally:
                release.set()
                self.until(lambda: self.window.worker is None)
        self.assertEqual(self.window.file_names, ["Mock acquisition"])
        self.assertTrue(self.window.acquire_button.isEnabled())

    def test_failed_acquisition_does_not_leave_ghost_name(self):
        self.window = SpectrometerApp(demo=False, port="FAKE")
        with patch("Spektrometar.activate_and_read_spectrometer", side_effect=SpectrometerError("Mock timeout")), \
                patch("Spektrometar.QInputDialog.getText", return_value=("Never completed", True)), \
                patch("Spektrometar.QMessageBox.warning") as warning:
            self.window.acquire_data()
            self.until(lambda: self.window.worker is None)
        self.assertEqual(self.window.file_names, [])
        self.assertEqual(self.window.measurements, [])
        self.assertTrue(self.window.acquire_button.isEnabled())
        warning.assert_called_once()

    def test_close_requests_cancellation_and_waits_for_worker(self):
        self.window = SpectrometerApp(demo=False, port="FAKE")
        entered = threading.Event()

        def acquire(*args, cancelled, **kwargs):
            entered.set()
            deadline = time.monotonic() + 2
            while not cancelled() and time.monotonic() < deadline:
                time.sleep(0.005)
            raise SpectrometerError("Acquisition cancelled.")

        with patch("Spektrometar.activate_and_read_spectrometer", side_effect=acquire), \
                patch("Spektrometar.QInputDialog.getText", return_value=("Cancelled", True)):
            self.window.show()
            self.window.acquire_data()
            self.until(entered.is_set)
            self.window.close()
            self.assertTrue(self.window.closing)
            self.until(lambda: self.window.worker is None)
        self.assertEqual(self.window.measurements, [])


if __name__ == "__main__":
    unittest.main()
