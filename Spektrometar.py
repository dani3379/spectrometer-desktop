"""Spectrometer desktop UI, curated from the recovered Spektrometar.py."""

import argparse
import sys
from pathlib import Path

from matplotlib.figure import Figure
from matplotlib import get_data_path
from PyQt5.QtWidgets import QApplication, QMainWindow, QVBoxLayout, QWidget, QPushButton, QLabel, QAction, QFileDialog, \
    QCheckBox, QInputDialog, QHBoxLayout,QMessageBox
from PyQt5.QtCore import QTimer, QThread, pyqtSignal

from matplotlib.backends.backend_qt5agg import FigureCanvasQTAgg as FigureCanvas
from spectrometer_driver import activate_and_read_spectrometer
from measurements import (demo_measurements, format_measurements, load_measurements,
                          pearson_correlation, validate_name, validate_spectrum)
from matplotlib.backends.backend_qt5agg import NavigationToolbar2QT as NavigationToolbar
from PyQt5.QtCore import Qt
from PyQt5.QtGui import QFont, QFontDatabase
from PyQt5.QtWidgets import QMenu


class AcquisitionWorker(QThread):
    """Serial IO runs off the GUI thread; widgets are updated only via signals."""
    acquired = pyqtSignal(object, object)
    failed = pyqtSignal(str)

    def __init__(self, port=None, timeout=10.0, parent=None):
        super().__init__(parent)
        self.port = port
        self.timeout = timeout

    def run(self):
        try:
            x, y = activate_and_read_spectrometer(
                self.port, timeout=self.timeout, cancelled=self.isInterruptionRequested)
            self.acquired.emit(x, y)
        except Exception as exc:
            self.failed.emit(str(exc))


class CheckboxWithRightClick(QCheckBox):
    def __init__(self, text, app_reference, parent=None):
        super().__init__(text, parent)
        self.app_reference = app_reference  # Reference to SpectrometerApp instance

    def mousePressEvent(self, event):
        if event.button() == Qt.RightButton:
            self.app_reference.show_context_menu(self)  # Use explicit app reference
        else:
            super().mousePressEvent(event)

class PlotCanvas(FigureCanvas):
    def __init__(self):
        self.fig = Figure()
        self.ax = self.fig.subplots()
        super().__init__(self.fig)

    def plot_data(self, x_data, y_data, label):
        self.ax.plot(x_data, y_data, label=label)

    def clear_plot(self):
        self.ax.clear()

    def draw_plot(self):
        if self.ax.lines:
            self.ax.legend()
        self.ax.set_xlabel('Wavelength (device units; demo: nm)')
        self.ax.set_ylabel('Intensity (arbitrary units)')
        self.ax.set_title('Spectral measurements')
        self.draw()


class SpectrometerApp(QMainWindow):
    def __init__(self, *, demo=True, port=None, timeout=10.0):

        super().__init__()
        # Qt's offscreen plugin may expose no system fonts. Matplotlib already
        # includes DejaVu Sans; load it only as a fallback for those environments.
        if not QFontDatabase().families():
            font_file = Path(get_data_path()) / "fonts" / "ttf" / "DejaVuSans.ttf"
            font_id = QFontDatabase.addApplicationFont(str(font_file))
            families = QFontDatabase.applicationFontFamilies(font_id)
            if families:
                QApplication.instance().setFont(QFont(families[0], 10))
        self.setWindowTitle("Spectrometer Desktop — " + ("Offline demo" if demo else "Serial acquisition"))
        self.setGeometry(400, 120, 1200, 700)
        self.demo_mode = demo
        self.port = port
        self.timeout = timeout
        self.worker = None
        self.pending_name = None
        self.closing = False
        self.measurements = []  # Списък за съхранение на данни за измервания
        self.checkbox_labels = {}  # Речник за съхранение на етикетите на отметките
        self.file_names = []
        self.color_index = 0
        self.measurement_colors = {}
        self.color_palette = [
            "#1f77b4", "#ff7f0e", "#2ca02c", "#d62728", "#9467bd", "#8c564b", "#e377c2", "#7f7f7f", "#bcbd22", "#17becf"
        ]  #
        self.setup_ui()
        if self.demo_mode:
            self.load_demo()

    def _unique_name(self, name):
        name = validate_name(name)
        candidate, suffix = name, 2
        while candidate in self.file_names:
            candidate = f"{name} ({suffix})"
            suffix += 1
        return candidate

    def add_measurement(self, name, x_data, y_data):
        x_data, y_data = validate_spectrum(x_data, y_data)
        name = self._unique_name(name)
        self.file_names.append(name)
        self.measurements.append((x_data, y_data))
        self.add_checkbox(len(self.measurements) - 1)

    def load_demo(self):
        for name, x_data, y_data in demo_measurements():
            self.add_measurement(name, x_data, y_data)
        self.update_plot()
        self.statusBar().showMessage("Synthetic demo data loaded. No hardware connection was opened.")

    def rename_checkbox(self, checkbox):
        """Rename the measurement associated with the checkbox."""
        current_name = checkbox.text()
        new_name, ok_pressed = QInputDialog.getText(self, "Rename measurement",
                                                    f"Enter a new name for '{current_name}':")
        if ok_pressed:
            try:
                new_name = validate_name(new_name)
                if new_name != current_name and new_name in self.file_names:
                    raise ValueError("A measurement with this name already exists.")
            except ValueError as exc:
                QMessageBox.warning(self, "Rename measurement", str(exc))
                return
            # Preserve the color by copying the current color to the new name
            if current_name in self.measurement_colors:
                self.measurement_colors[new_name] = self.measurement_colors.pop(current_name)

            # Update the checkbox text
            checkbox.setText(new_name)

            # Update the data structures
            index = self.file_names.index(current_name)
            self.file_names[index] = new_name  # Update file_names with the new name
            self.checkbox_labels[checkbox] = new_name  # Update checkbox_labels

            # Refresh the plot
            self.update_plot()

    def delete_checkbox(self, checkbox):
        """Delete the measurement associated with the checkbox."""
        try:
            # Get the measurement name from the checkbox
            measurement_name = self.checkbox_labels[checkbox]
            print(f"Measurement to delete: {measurement_name}")

            # Find the index of the measurement in file_names
            index = self.file_names.index(measurement_name)

            # Remove the measurement data
            self.measurements.pop(index)
            self.file_names.pop(index)
            self.measurement_colors.pop(measurement_name, None)

            # Remove the checkbox from checkbox_labels
            del self.checkbox_labels[checkbox]

            # Remove the checkbox from the layout and delete it
            self.checkbox_layout.removeWidget(checkbox)
            checkbox.deleteLater()

            # Reassign indices and reconnect checkboxes to update_plot
            self.reassign_checkbox_indices()

            # Update the plot to reflect changes
            self.update_plot()

            print("Checkbox and associated measurement deleted successfully.")
        except Exception as e:
            QMessageBox.warning(self, "Delete measurement", str(e))

    def compare_checkbox(self, checkbox):
        """Compare the measurement associated with the checkbox to another measurement."""
        measurement_name = checkbox.text()
        index1 = list(self.checkbox_labels.values()).index(measurement_name)

        # Let the user select a second measurement
        other_measurements = [name for name in self.file_names if name != measurement_name]
        if not other_measurements:
            QMessageBox.warning(self, "Compare", "No other measurements to compare.")
            return

        measurement2, ok_pressed = QInputDialog.getItem(self, "Choose a measurement to compare", "Measurement:",
                                                        other_measurements, 0, False)
        if ok_pressed:
            index2 = self.file_names.index(measurement2)
            self.compare_measurements(index1, index2)

    def reassign_checkbox_indices(self):
        """Reassign indices and reconnect checkboxes to update_plot after a deletion."""
        # The dictionary retains insertion order and checkbox callbacks read
        # current state; there are no stale captured list indices to rewire.
        for index, checkbox in enumerate(self.checkbox_labels):
            self.checkbox_labels[checkbox] = self.file_names[index]

    def show_context_menu(self, checkbox):
        """Displays a context menu when a checkbox is right-clicked."""
        menu = QMenu(self)

        # Add rename option
        rename_action = QAction("Rename", self)
        rename_action.triggered.connect(lambda: self.rename_checkbox(checkbox))
        menu.addAction(rename_action)

        # Add delete option
        delete_action = QAction("Delete", self)
        delete_action.triggered.connect(lambda: self.delete_checkbox(checkbox))
        menu.addAction(delete_action)

        # Add compare option
        compare_action = QAction("Compare", self)
        compare_action.triggered.connect(lambda: self.compare_checkbox(checkbox))
        menu.addAction(compare_action)

        # Show the menu at the checkbox's position
        menu.exec_(checkbox.mapToGlobal(checkbox.rect().center()))

    def compare_measurements(self, index1, index2):
        try:
            name1, name2 = self.file_names[index1], self.file_names[index2]
            correlation = pearson_correlation(self.measurements[index1], self.measurements[index2])

            # Display results
            QMessageBox.information(self, "Comparison results",
                                    f"Measurement 1: {name1}\n"
                                    f"Measurement 2: {name2}\n\n"
                                    f"Pearson correlation: {correlation * 100:.2f}%\n"
                                    )
        except Exception as e:
            QMessageBox.warning(self, "Compare measurements", str(e))

    def prompt_and_compare(self):
        measurements_list = [checkbox.text() for checkbox in self.checkbox_labels.keys()]
        if len(measurements_list) < 2:
            QMessageBox.warning(self, "Notice", "At least two measurements are needed.")
            print("Not enough measurements to compare.")
            return

        measurement1, ok1 = QInputDialog.getItem(self, "Choose first measurement", "Measurement:", measurements_list, 0,
                                                 False)
        if not ok1:
            return
        measurement2, ok2 = QInputDialog.getItem(self, "Choose second measurement", "Measurement:", measurements_list, 1,
                                                 False)

        if ok1 and ok2:
            index1 = measurements_list.index(measurement1)
            index2 = measurements_list.index(measurement2)
            self.compare_measurements(index1, index2)

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self.adjust_window_height()

    def adjust_window_height(self):
        if not hasattr(self, "checkbox_layout"):
            return
        required_height = self.checkbox_layout.sizeHint().height()
        current_height = self.height()
        if required_height > current_height:
            self.resize(self.width(), min(required_height, 900))

    def create_menu_bar(self):
        menubar = self.menuBar()
        file_menu = menubar.addMenu('&File')
        measurement_menu = menubar.addMenu('&Measurements')

        # "Open measurements" action
        open_action = QAction('&Open measurements', self)
        open_action.setShortcut('Ctrl+O')
        open_action.triggered.connect(self.open_data)
        file_menu.addAction(open_action)

        # "Save measurements" action
        save_action = QAction('&Save measurements', self)
        save_action.setShortcut('Ctrl+S')
        save_action.triggered.connect(self.save_data)
        file_menu.addAction(save_action)

        # "Export plot" action
        save_image_action = QAction('&Export plot', self)
        save_image_action.setShortcut('Ctrl+I')
        save_image_action.triggered.connect(self.save_image)
        file_menu.addAction(save_image_action)

        # "Rename measurement" action
        rename_action = QAction('&Rename measurement', self)
        rename_action.setShortcut('Ctrl+R')
        rename_action.triggered.connect(self.rename_measurement)
        measurement_menu.addAction(rename_action)

        # "Clear measurements" action
        clear_action = QAction('&Clear measurements', self)
        clear_action.setShortcut('Ctrl+L')
        clear_action.triggered.connect(self.clear_all_data)
        measurement_menu.addAction(clear_action)

        # "Compare measurements" action
        compare_action = QAction('&Compare measurements', self)
        compare_action.setShortcut('Ctrl+M')
        compare_action.triggered.connect(self.prompt_and_compare)
        measurement_menu.addAction(compare_action)

        demo_action = QAction('Load synthetic demo', self)
        demo_action.triggered.connect(self.load_demo)
        menubar.addAction(demo_action)

    def setup_ui(self):

        # Main layout: horizontal layout for plot and right controls
        main_layout = QHBoxLayout()

        # Left vertical layout for plot and instructions
        left_layout = QVBoxLayout()
        left_layout.setContentsMargins(10, 10, 5, 10)  # Adjust margins for better spacing
        left_layout.setSpacing(10)

        # Instruction label
        self.instruction_label = QLabel(
            "Offline demo: generated sample curves; no device connection."
            if self.demo_mode else "Serial mode: click Acquire to trigger a measurement; files and demo also work offline.")
        self.instruction_label.setWordWrap(True)
        left_layout.addWidget(self.instruction_label)

        # Matplotlib canvas
        self.canvas = PlotCanvas()
        left_layout.addWidget(self.canvas, stretch=1)  # Set stretch to make it expand

        # Add NavigationToolbar for zooming
        toolbar = NavigationToolbar(self.canvas, self)
        left_layout.addWidget(toolbar, stretch=0)  # Toolbar takes minimal space

        # Add the left layout to the main layout
        main_layout.addLayout(left_layout, stretch=3)  # Left layout takes more space

        # Middle vertical layout for button and checkboxes
        middle_layout = QVBoxLayout()
        middle_layout.setContentsMargins(5, 10, 5, 10)  # Adjust margins
        middle_layout.setSpacing(10)

        # "Take Measurement" button
        self.acquire_button = QPushButton("Add synthetic measurement" if self.demo_mode else "Acquire measurement")
        self.acquire_button.clicked.connect(self.acquire_data)

        # Set the button's height and width for better appearance
        self.acquire_button.setFixedHeight(50)
        self.acquire_button.setMinimumWidth(220)  # Increase the button's width
        self.acquire_button.setStyleSheet("font-size: 16px;")
        middle_layout.addWidget(self.acquire_button, alignment=Qt.AlignTop | Qt.AlignHCenter)

        # Lower the "Take Measurement" button
        middle_layout.addSpacing(20)  # Add space below the button

        # Checkbox layout for measurements
        self.checkbox_layout = QVBoxLayout()
        self.checkbox_layout.setSpacing(0)
        self.checkbox_layout.setContentsMargins(0, 0, 0, 0)
        middle_layout.addLayout(self.checkbox_layout)

        # Add stretch to push the button and checkboxes to the top
        middle_layout.addStretch()

        # Add the middle layout to the main layout
        middle_widget = QWidget()
        middle_widget.setLayout(middle_layout)
        main_layout.addWidget(middle_widget, stretch=1)  # Middle layout takes less space

        # Set layout to the central widget
        widget = QWidget()
        widget.setLayout(main_layout)
        self.setCentralWidget(widget)

        self.create_menu_bar()

    def clear_all_data(self):
        self.measurements = []
        self.checkbox_labels = {}
        self.file_names = []
        self.measurement_colors = {}
        self.color_index = 0
        self.canvas.clear_plot()  # Изчистване на графиката
        for i in reversed(range(self.checkbox_layout.count())):
            widget = self.checkbox_layout.itemAt(i).widget()
            if widget is not None:
                self.checkbox_layout.removeWidget(widget)
                widget.deleteLater()  # Delete на отметките
        self.update_plot()  # Обновяване на графиката след изчистване

    def update_plot(self):
        """Update the plot with only the active (checked) measurements."""
        self.canvas.clear_plot()
        for index, (x_data, y_data) in enumerate(self.measurements):
            # Get the measurement name
            measurement_name = self.file_names[index]

            # Check if the checkbox for this measurement is active
            checkbox = list(self.checkbox_labels.keys())[index]
            if checkbox.isChecked():
                # Retrieve or assign the fixed color for this measurement
                color = self.get_measurement_color(measurement_name)

                # Plot the data with the measurement name and fixed color
                self.canvas.ax.plot(x_data, y_data, label=measurement_name, color=color)

        # Ensure legend is redrawn and maintains order
        self.canvas.draw_plot()

    def get_measurement_color(self, measurement_name):
        """Retrieve or assign a consistent color for a given measurement."""
        if measurement_name not in self.measurement_colors:
            # Assign a new color if not already assigned
            if self.color_index >= len(self.color_palette):
                self.color_index = 0  # Loop back to the beginning of the palette
            self.measurement_colors[measurement_name] = self.color_palette[self.color_index]
            self.color_index += 1
        return self.measurement_colors[measurement_name]

    def add_checkbox(self, index):
        measurement_name = self.file_names[index]
        color = self.get_measurement_color(measurement_name)

        # Create a new checkbox
        checkbox = CheckboxWithRightClick(measurement_name, self)  # Pass the app instance for the context menu
        checkbox.setChecked(True)
        checkbox.setMinimumWidth(220)
        checkbox.setFixedHeight(45)
        checkbox.setStyleSheet(f"""
            QCheckBox {{
                font-size: 16px;
                font-weight: bold;
                background-color: {color};
                color: black;
                border-radius: 0px;  /* Rounded corners for the colored area */
                padding-left: 10px;  /* Space between text and checkbox indicator */
            }}
            QCheckBox::indicator {{
                width: 15px;  /* Keep the indicator size proportional */
                height: 15px;
                border-radius: 4px;  /* Make the checkbox rounded */
                border: 1px solid black;  /* Black border for the checkbox */
                background-color: white;  /* Default color for unchecked state */
            }}
            QCheckBox::indicator:checked {{
                background-color: #198754;
                border: 2px solid green;  /* Green border for checked state */
                /* A solid checked state avoids an undocumented external icon. */
                background-repeat: no-repeat;
                background-position: center;
            }}
            QCheckBox::indicator:unchecked {{
                background-color: white;  /* White fill for the unchecked checkbox */
                border: 2px solid black;  /* Black border when unchecked */
            }}
        """)

        checkbox.stateChanged.connect(lambda state, index=index: self.update_plot())

        # Add the checkbox to the layout
        self.checkbox_layout.addWidget(checkbox)

        # Update the mapping: use `checkbox` as the key instead of an index
        self.checkbox_labels[checkbox] = measurement_name

    def rename_measurement(self):
        """Rename a measurement using the menu option."""
        # Get the actual names of measurements from checkboxes
        measurements_list = [checkbox.text() for checkbox in self.checkbox_labels.keys()]

        if not measurements_list:
            QMessageBox.warning(self, "Error", "No measurements available to rename.")
            return

        # Prompt the user to select a measurement to rename
        measurement, ok_pressed = QInputDialog.getItem(self, "Rename measurement", "Choose a measurement:",
                                                       measurements_list, 0, False)
        if ok_pressed and measurement:
            checkbox = next(box for box, name in self.checkbox_labels.items() if name == measurement)
            self.rename_checkbox(checkbox)

    def save_data(self):
        file_path, _ = QFileDialog.getSaveFileName(self, "Save measurements", "", "Text files (*.txt)")

        if file_path:
            try:
                selected = [
                    (name, *self.measurements[index])
                    for index, (checkbox, name) in enumerate(self.checkbox_labels.items())
                    if checkbox.isChecked()
                ]
                text = format_measurements(selected)
                Path(file_path).write_text(text, encoding="utf-8")
                self.statusBar().showMessage("Measurements saved.")
            except Exception as e:
                QMessageBox.warning(self, "Save measurements", str(e))

    def open_data(self):
        options = QFileDialog.Options()
        options |= QFileDialog.DontUseNativeDialog
        file_path, _ = QFileDialog.getOpenFileName(self, "Open measurements", "", "Text files (*.txt)",
                                                   options=options)
        if file_path:
            try:
                measurements = load_measurements(file_path)
                for name, x_data, y_data in measurements:
                    self.add_measurement(name, x_data, y_data)
                self.update_plot()  # Redraw the plot
                self.statusBar().showMessage(f"Loaded {len(measurements)} measurements.")
            except Exception as e:
                QMessageBox.warning(self, "Open measurements", str(e))

    def acquire_data(self):

        if self.worker is not None:
            return
        new_name, accepted = QInputDialog.getText(self, "Measurement name", "Name for the new measurement:")
        if not accepted:
            return
        try:
            new_name = validate_name(new_name)
        except ValueError as exc:
            QMessageBox.warning(self, "Measurement name", str(exc))
            return
        if self.demo_mode:
            _, x_data, y_data = demo_measurements()[1]
            self.add_measurement(new_name, x_data, y_data)
            self.update_plot()
            self.statusBar().showMessage("Added a synthetic measurement; no device connection.")
            return
        self.pending_name = new_name
        self.acquire_button.setEnabled(False)
        self.statusBar().showMessage("Acquiring... the interface remains available.")
        self.worker = AcquisitionWorker(self.port, self.timeout, self)
        self.worker.acquired.connect(self._acquisition_succeeded)
        self.worker.failed.connect(self._acquisition_failed)
        self.worker.finished.connect(self._acquisition_finished)
        self.worker.start()

    def _acquisition_succeeded(self, x_data, y_data):
        if not self.closing:
            self.add_measurement(self.pending_name, x_data, y_data)
            self.update_plot()
            self.statusBar().showMessage("Measurement acquired.")

    def _acquisition_failed(self, message):
        if not self.closing:
            self.statusBar().showMessage("Acquisition failed; no partial measurement added.")
            QMessageBox.warning(self, "Acquisition failed", message)

    def _acquisition_finished(self):
        self.worker.deleteLater()
        self.worker = None
        self.pending_name = None
        self.acquire_button.setEnabled(True)
        if self.closing:
            QTimer.singleShot(0, self.close)

    def closeEvent(self, event):
        if self.worker is not None and self.worker.isRunning():
            self.closing = True
            self.worker.requestInterruption()
            self.statusBar().showMessage("Stopping acquisition before closing...")
            event.ignore()
            return
        super().closeEvent(event)

    def save_image(self):
        file_path, _ = QFileDialog.getSaveFileName(self, "Export plot", "", "Images (*.png *.jpg *.jpeg *.pdf)")
        if file_path:
            try:
                self.canvas.fig.savefig(file_path)
                self.statusBar().showMessage("Plot exported.")
            except Exception as e:
                QMessageBox.warning(self, "Export plot", str(e))


def main(argv=None):
    parser = argparse.ArgumentParser(description="Spectrometer plotting and serial acquisition desktop app.")
    modes = parser.add_mutually_exclusive_group()
    modes.add_argument("--demo", action="store_true", help="Start with synthetic measurements (default).")
    modes.add_argument("--hardware", action="store_true", help="Enable serial measurement acquisition.")
    parser.add_argument("--port", help="Serial port, e.g. COM3 or /dev/ttyUSB0; requires --hardware.")
    parser.add_argument("--timeout", type=float, default=10.0, help="Acquisition deadline in seconds (0 < n <= 60).")
    args = parser.parse_args(argv)
    if not 0 < args.timeout <= 60:
        parser.error("--timeout must be between 0 and 60 seconds.")
    if args.port and not args.hardware:
        parser.error("--port requires --hardware.")
    app = QApplication(sys.argv)
    spectrometer_app = SpectrometerApp(demo=not args.hardware, port=args.port, timeout=args.timeout)
    spectrometer_app.show()
    return app.exec_()


if __name__ == "__main__":
    sys.exit(main())
