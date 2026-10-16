import unittest

from tcp_keepalive_configuration import KeepaliveOptions, compute_keepalive
from tcp_keepalive_configuration.core import (
    _clamp_ms,
    _validate,
    _WINDOWS_MAX_MS,
)


class TestValidation(unittest.TestCase):
    def test_rejects_zero_idle(self):
        with self.assertRaises(ValueError):
            compute_keepalive("linux", 0, 10, 3)

    def test_rejects_negative_idle(self):
        with self.assertRaises(ValueError):
            compute_keepalive("linux", -1, 10, 3)

    def test_rejects_zero_interval(self):
        with self.assertRaises(ValueError):
            compute_keepalive("linux", 10, 0, 3)

    def test_rejects_zero_count(self):
        with self.assertRaises(ValueError):
            compute_keepalive("linux", 10, 10, 0)

    def test_rejects_unknown_platform(self):
        with self.assertRaises(ValueError):
            compute_keepalive("plan9", 10, 10, 3)

    def test_platform_is_case_insensitive(self):
        # We lower() the platform key so callers do not have to guess.
        opts = compute_keepalive("Linux", 10, 10, 3)
        self.assertEqual(opts.enable, 1)

    def test_validate_directly(self):
        # _validate is part of the module's behaviour; confirm the happy path
        # does not raise.
        _validate(1, 1, 1)


class TestLinux(unittest.TestCase):
    def test_basic_values(self):
        opts = compute_keepalive("linux", 30, 10, 3)
        self.assertIsInstance(opts, KeepaliveOptions)
        self.assertEqual(opts.enable, 1)
        # Linux uses seconds directly.
        self.assertEqual(opts.options[(0xFFFF, 0x0009)], 1)
        self.assertEqual(opts.options[(6, 4)], 30)
        self.assertEqual(opts.options[(6, 5)], 10)
        self.assertEqual(opts.options[(6, 6)], 3)

    def test_order_is_enable_first(self):
        opts = compute_keepalive("linux", 30, 10, 3)
        first_key = next(iter(opts.options))
        self.assertEqual(first_key, (0xFFFF, 0x0009))

    def test_float_seconds_are_truncated_to_int(self):
        # int() truncates toward zero; this documents that choice.
        opts = compute_keepalive("linux", 30.9, 10.9, 3)
        self.assertEqual(opts.options[(6, 4)], 30)
        self.assertEqual(opts.options[(6, 5)], 10)


class TestMacos(unittest.TestCase):
    def test_basic_values(self):
        opts = compute_keepalive("macos", 60, 15, 5)
        self.assertEqual(opts.enable, 1)
        self.assertEqual(opts.options[(0xFFFF, 0x0008)], 1)
        self.assertEqual(opts.options[(6, 0x10)], 60)
        self.assertEqual(opts.options[(6, 0x101)], 15)
        self.assertEqual(opts.options[(6, 0x102)], 5)


class TestWindows(unittest.TestCase):
    def test_converts_to_milliseconds(self):
        opts = compute_keepalive("windows", 30, 10, 3)
        self.assertEqual(opts.enable, 1)
        sio = (0xFFFF, 0x98000004)
        onoff, idle_ms, interval_ms, count = opts.options[sio]
        self.assertEqual(onoff, 1)
        self.assertEqual(idle_ms, 30000)
        self.assertEqual(interval_ms, 10000)
        self.assertEqual(count, 3)

    def test_millisecond_truncation(self):
        # 30.9999 s -> 30999 ms after truncation, not rounded up.
        opts = compute_keepalive("windows", 30.9999, 10.5, 2)
        _, idle_ms, interval_ms, _ = opts.options[(0xFFFF, 0x98000004)]
        self.assertEqual(idle_ms, 30999)
        self.assertEqual(interval_ms, 10500)

    def test_huge_seconds_are_capped(self):
        # A value that fits comfortably in seconds but overflows once x1000.
        # 5_000_000 s -> 5_000_000_000 ms, which exceeds 0xFFFFFFFF.
        opts = compute_keepalive("windows", 5_000_000, 5_000_000, 9)
        _, idle_ms, interval_ms, _ = opts.options[(0xFFFF, 0x98000004)]
        self.assertEqual(idle_ms, _WINDOWS_MAX_MS)
        self.assertEqual(interval_ms, _WINDOWS_MAX_MS)


class TestClampMs(unittest.TestCase):
    def test_sub_second_floors(self):
        self.assertEqual(_clamp_ms(0.001), 1)
        self.assertEqual(_clamp_ms(0.0009), 0)

    def test_at_boundary(self):
        # Exactly the max should pass through unchanged.
        self.assertEqual(_clamp_ms(_WINDOWS_MAX_MS / 1000), _WINDOWS_MAX_MS)

    def test_over_boundary_caps(self):
        self.assertEqual(_clamp_ms((_WINDOWS_MAX_MS + 1) / 1000), _WINDOWS_MAX_MS)

    def test_negative_raises(self):
        with self.assertRaises(ValueError):
            _clamp_ms(-0.1)


class TestSetsockoptPairs(unittest.TestCase):
    def test_yields_triples(self):
        opts = compute_keepalive("linux", 30, 10, 3)
        triples = list(opts.to_setsockopt_pairs())
        self.assertEqual(triples[0], (0xFFFF, 0x0009, 1))
        self.assertEqual(triples[1], (6, 4, 30))
        self.assertEqual(triples[2], (6, 5, 10))
        self.assertEqual(triples[3], (6, 6, 3))


if __name__ == "__main__":
    unittest.main()
