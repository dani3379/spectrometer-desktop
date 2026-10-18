import tempfile
import unittest
from pathlib import Path

import numpy as np

from measurements import (demo_measurements, format_measurements, load_measurements,
                          parse_measurements, pearson_correlation, validate_spectrum)


class MeasurementTests(unittest.TestCase):
    def test_demo_is_deterministic_and_independent(self):
        first, second = demo_measurements(), demo_measurements()
        self.assertEqual(len(first), 2)
        for (name, x, y), (other_name, other_x, other_y) in zip(first, second):
            self.assertEqual(name, other_name)
            np.testing.assert_array_equal(x, other_x)
            np.testing.assert_array_equal(y, other_y)
            self.assertEqual(len(x), 176)
        first[0][1][0] = -1
        self.assertEqual(first[1][1][0], 400)
        self.assertEqual(second[0][1][0], 400)

    def test_named_text_format_round_trips_precision_and_unicode(self):
        expected = [("Синтетичен образец", [400.1234567890123, 401], [1.2, 3.5])]
        actual = parse_measurements(format_measurements(expected))
        self.assertEqual(actual[0][0], expected[0][0])
        np.testing.assert_array_equal(actual[0][1], expected[0][1])
        np.testing.assert_array_equal(actual[0][2], expected[0][2])

    def test_legacy_crlf_multiple_blank_lines(self):
        parsed = parse_measurements("First\r\n400, 2\r\n401, 3\r\n\r\n\r\nSecond\r\n400, 5\r\n401, 6\r\n")
        self.assertEqual([item[0] for item in parsed], ["First", "Second"])

    def test_legacy_bulgarian_windows_encoding(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "measurement.txt"
            path.write_bytes("Образец\n400, 2\n401, 3\n".encode("cp1251"))
            self.assertEqual(load_measurements(path)[0][0], "Образец")

    def test_malformed_files_are_rejected(self):
        for text in ("", "Empty name\n", "One point\n400,1", "Bad\n400,1,2\n401,3",
                     "Bad\n400,nan\n401,3", "Bad\n400,nope\n401,3",
                     "Valid\n400,1\n401,2\n\nBroken\n400,1"):
            with self.subTest(text=text), self.assertRaises(ValueError):
                parse_measurements(text)

    def test_invalid_shape_and_nonfinite_data(self):
        for x, y in (([1], [2]), ([1, 2], [1]), ([[1, 2]], [[1, 2]]), ([1, 2], [1, np.inf])):
            with self.subTest(x=x, y=y), self.assertRaises(ValueError):
                validate_spectrum(x, y)

    def test_empty_or_multiline_export_names_are_rejected(self):
        for name in ("", " ", "First\nSecond"):
            with self.subTest(name=name), self.assertRaises(ValueError):
                format_measurements([(name, [1, 2], [3, 4])])
        with self.assertRaises(ValueError):
            format_measurements([])

    def test_correlation_has_known_positive_and_negative_values(self):
        x = [400, 401, 402]
        self.assertAlmostEqual(pearson_correlation((x, [1, 2, 3]), (x, [3, 5, 7])), 1.0)
        self.assertAlmostEqual(pearson_correlation((x, [1, 2, 3]), (x, [9, 5, 1])), -1.0)

    def test_constant_and_unaligned_spectra_are_rejected(self):
        with self.assertRaisesRegex(ValueError, "constant"):
            pearson_correlation(([1, 2], [3, 3]), ([1, 2], [4, 5]))
        for other in (([1, 3], [4, 5]), ([1, 2, 3], [4, 5, 6])):
            with self.subTest(other=other), self.assertRaisesRegex(ValueError, "grids"):
                pearson_correlation(([1, 2], [3, 4]), other)

    def test_correlation_avoids_overflow_for_large_finite_values(self):
        x, y = [1, 2, 3], [-1e308, 0, 1e308]
        self.assertAlmostEqual(pearson_correlation((x, y), (x, y)), 1.0)


if __name__ == "__main__":
    unittest.main()
