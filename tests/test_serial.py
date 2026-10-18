import unittest
from unittest.mock import patch

import numpy as np
import serial

from spectrometer_driver import (SpectrometerError, activate_and_read_spectrometer,
                                 find_spectrometer_port, parse_serial_line, read_spectrum)


class FakeSerial:
    def __init__(self, lines=(), error=None):
        self.lines = iter(lines)
        self.error = error
        self.closed = False
        self.writes = []

    def read_until(self, expected=b"\n", size=256):
        if self.error is not None:
            raise self.error
        return next(self.lines, b"")

    def write(self, command):
        self.writes.append(command)
        return len(command)

    def close(self):
        self.closed = True


class TickingClock:
    def __init__(self):
        self.now = 0

    def __call__(self):
        self.now += 0.25
        return self.now


class SerialTests(unittest.TestCase):
    def test_protocol_numeric_row_end_and_chatter(self):
        self.assertEqual(parse_serial_line(b"x=d,450.5,y=v,123.2\r\n"), (450.5, 123.2))
        self.assertEqual(parse_serial_line(b"x=e\r\n"), "end")
        self.assertIsNone(parse_serial_line(b"device ready\n"))

    def test_bad_rows_are_rejected(self):
        for row in (b"x=d,1,2", b"x=d,one,y=v,2", b"x=d,nan,y=v,2", b"x=d,1,,2", b"\xff"):
            with self.subTest(row=row), self.assertRaises(SpectrometerError):
                parse_serial_line(row)

    def test_complete_transfer_handles_fragmented_rows(self):
        connection = FakeSerial([b"boot\n", b"x=d,40", b"0,y=v,3\n", b"x=d,401,y=v,4\n", b"x=e\n"])
        x, y = read_spectrum(connection)
        np.testing.assert_array_equal(x, [400, 401])
        np.testing.assert_array_equal(y, [3, 4])

    def test_missing_end_marker_hits_deadline(self):
        with self.assertRaisesRegex(SpectrometerError, "timed out"):
            read_spectrum(FakeSerial([b"x=d,400,y=v,3\n"]), timeout=1, clock=TickingClock())

    def test_cancelled_acquisition_stops(self):
        with self.assertRaisesRegex(SpectrometerError, "cancelled"):
            read_spectrum(FakeSerial(), cancelled=lambda: True)

    def test_empty_and_oversized_measurements_are_rejected(self):
        for rows in ([b"x=e\n"], [b"a" * 256],
                     [b"x=d,400,y=v,1\n", b"x=d,401,y=v,2\n", b"x=d,402,y=v,3\n"]):
            with self.subTest(rows=rows), self.assertRaises(SpectrometerError):
                read_spectrum(FakeSerial(rows), max_points=2)

    def test_connection_is_closed_on_success_and_failure(self):
        cases = [([b"x=d,400,y=v,3\n", b"x=d,401,y=v,4\n", b"x=e\n"], None),
                 ([b"x=d,not-a-number,y=v,3\n"], SpectrometerError)]
        for rows, error in cases:
            connection = FakeSerial(rows)
            factory = unittest.mock.Mock(return_value=connection)
            if error:
                with self.assertRaises(error):
                    activate_and_read_spectrometer("FAKE", serial_factory=factory)
            else:
                activate_and_read_spectrometer("FAKE", serial_factory=factory)
            self.assertTrue(connection.closed)
            self.assertEqual(connection.writes, [b"m"])
            self.assertEqual(factory.call_args.kwargs["timeout"], 0.2)

    def test_disconnect_is_reported_and_connection_closed(self):
        connection = FakeSerial(error=serial.SerialException("mock device disconnected"))
        with self.assertRaisesRegex(SpectrometerError, "communicate"):
            activate_and_read_spectrometer("FAKE", serial_factory=lambda *a, **k: connection)
        self.assertTrue(connection.closed)

    def test_missing_or_ambiguous_port_has_actionable_error(self):
        with patch("spectrometer_driver.list_ports.comports", return_value=[]):
            with self.assertRaisesRegex(SpectrometerError, "No Arduino"):
                activate_and_read_spectrometer()
        port = unittest.mock.Mock(device="FAKE", description="Arduino")
        with patch("spectrometer_driver.list_ports.comports", return_value=[port, port]):
            with self.assertRaisesRegex(SpectrometerError, "Several"):
                find_spectrometer_port()

    def test_invalid_deadline_is_rejected_before_opening_device(self):
        for timeout in (0, -1, 61, float("nan"), float("inf")):
            with self.subTest(timeout=timeout), self.assertRaises(ValueError):
                activate_and_read_spectrometer("FAKE", timeout=timeout)


if __name__ == "__main__":
    unittest.main()
