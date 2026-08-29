"""Feasibility memory accounting must never report an absent measurement as 0.

The official 20k gate returned peak_rss_bytes = 0, which was indistinguishable
from a genuine reading of zero. A missing measurement has to be reported as
missing.
"""

from __future__ import absolute_import

import sys
import unittest

from .common import REPOSITORY_ROOT  # noqa: F401  (puts src/ on sys.path)

from adaptive_qmix import feasibility


class ResidentSetSizeTests(unittest.TestCase):
    def test_measurement_reports_a_value_and_its_source(self):
        value, source = feasibility.resident_set_size_bytes()
        self.assertIsInstance(source, str)
        if value is None:
            self.assertEqual(source, "unavailable")
        else:
            self.assertGreater(
                value, 0, "a successful RSS reading should be positive"
            )
            self.assertNotEqual(source, "unavailable")

    def test_a_supported_platform_has_at_least_one_working_path(self):
        """Linux, macOS and Windows must all resolve without psutil."""
        if not (sys.platform.startswith(("win", "linux", "darwin"))):
            raise unittest.SkipTest("platform outside the supported set")
        value, source = feasibility.resident_set_size_bytes()
        self.assertIsNotNone(
            value,
            "no RSS measurement path resolved on {} (source={})".format(
                sys.platform, source
            ),
        )

    def test_windows_uses_psapi_when_psutil_is_absent(self):
        if not sys.platform.startswith("win"):
            raise unittest.SkipTest("Windows-only measurement path")
        self.assertGreater(feasibility._windows_peak_working_set_bytes(), 0)


class FeasibilityReportTests(unittest.TestCase):
    def _report(self, meter):
        meter.start()
        meter.record_transition(1000, ".")
        return meter.finish()

    def test_unavailable_memory_is_null_not_zero(self):
        original = feasibility.resident_set_size_bytes
        feasibility.resident_set_size_bytes = lambda: (None, "unavailable")
        try:
            report = self._report(feasibility.FeasibilityMeter("qmix", 20000))
        finally:
            feasibility.resident_set_size_bytes = original
        self.assertIsNone(
            report["peak_rss_bytes"],
            "an unavailable measurement must not be reported as 0",
        )
        self.assertFalse(report["peak_rss_available"])
        self.assertEqual(report["peak_rss_source"], "unavailable")

    def test_available_memory_is_reported_with_its_source(self):
        original = feasibility.resident_set_size_bytes
        feasibility.resident_set_size_bytes = lambda: (4096, "stub")
        try:
            report = self._report(feasibility.FeasibilityMeter("qmix", 20000))
        finally:
            feasibility.resident_set_size_bytes = original
        self.assertEqual(report["peak_rss_bytes"], 4096)
        self.assertTrue(report["peak_rss_available"])
        self.assertEqual(report["peak_rss_source"], "stub")

    def test_peak_is_the_maximum_across_samples(self):
        original = feasibility.resident_set_size_bytes
        values = iter([100, 900, 400])
        feasibility.resident_set_size_bytes = lambda: (next(values), "stub")
        try:
            meter = feasibility.FeasibilityMeter("qmix", 20000)
            meter.start()
            for _ in range(3):
                meter.record_transition(1000, ".")
            report = meter.finish()
        finally:
            feasibility.resident_set_size_bytes = original
        self.assertEqual(report["peak_rss_bytes"], 900)

    def test_a_meter_that_never_sampled_reports_absence(self):
        meter = feasibility.FeasibilityMeter("qmix", 20000)
        meter.start()
        report = meter.finish()
        self.assertIsNone(report["peak_rss_bytes"])
        self.assertFalse(report["peak_rss_available"])
        self.assertEqual(report["peak_rss_source"], "not_sampled")


if __name__ == "__main__":
    unittest.main()
