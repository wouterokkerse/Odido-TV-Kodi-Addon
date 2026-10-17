"""Replay day boundaries must match the provider, including DST on Kodi builds
without an IANA timezone database.
"""
import datetime as dt
from pathlib import Path
import sys
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'plugin.video.odidotv'))
from resources.lib import tvtime


class TVTimeTests(unittest.TestCase):
    def test_summer_day_uses_amsterdam_not_host_timezone(self):
        start, end = tvtime.day_bounds('20260606')
        self.assertEqual(dt.datetime.fromtimestamp(start / 1000, dt.timezone.utc).isoformat(),
                         '2026-06-05T22:00:00+00:00')
        self.assertEqual(dt.datetime.fromtimestamp(end / 1000, dt.timezone.utc).isoformat(),
                         '2026-06-06T21:59:59+00:00')

    def test_winter_day_uses_standard_time(self):
        start, _ = tvtime.day_bounds('20260106')
        self.assertEqual(dt.datetime.fromtimestamp(start / 1000, dt.timezone.utc).hour, 23)

    def test_date_parsing_does_not_need_lazy_strptime_module(self):
        import builtins
        original = builtins.__import__
        def guarded(name, *args, **kwargs):
            if name == '_strptime':
                raise TypeError('Simulated unavailable Kodi date parser')
            return original(name, *args, **kwargs)
        with patch('builtins.__import__', side_effect=guarded):
            start, end = tvtime.day_bounds('20260606')
        self.assertLess(start, end)

    def test_invalid_dates_are_rejected(self):
        for day in ('20260230', '20261301', '2026066', '20260606extra'):
            with self.subTest(day=day), self.assertRaises(ValueError):
                tvtime.day_bounds(day)

    def test_dst_days_are_23_and_25_hours_in_both_timezone_paths(self):
        for zone in (tvtime.AMSTERDAM, None):
            with patch.object(tvtime, 'AMSTERDAM', zone):
                for day, hours in (('20260329', 23), ('20261025', 25)):
                    start, end = tvtime.day_bounds(day)
                    self.assertEqual(end + 1000 - start, hours * 3600000)

    def test_fallback_matches_iana_for_each_day_of_year(self):
        if tvtime.AMSTERDAM is None:
            self.skipTest('IANA database unavailable on test host')
        date = dt.date(2026, 1, 1)
        for offset in range(365):
            day = (date + dt.timedelta(days=offset)).strftime('%Y%m%d')
            expected = tvtime.day_bounds(day)
            with patch.object(tvtime, 'AMSTERDAM', None):
                self.assertEqual(tvtime.day_bounds(day), expected)

    def test_displayed_date_changes_at_amsterdam_midnight(self):
        instant = dt.datetime(2026, 6, 5, 22, 30, tzinfo=dt.timezone.utc).timestamp()
        for zone in (tvtime.AMSTERDAM, None):
            with patch.object(tvtime, 'AMSTERDAM', zone):
                self.assertEqual(tvtime.local_time(instant).strftime('%Y%m%d %H:%M'), '20260606 00:30')
