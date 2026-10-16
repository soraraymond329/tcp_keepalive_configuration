"""Compute per-socket TCP keepalive option values from a target spec.

The three numbers a user typically cares about are:

  idle    seconds of connection silence before the first probe
  interval seconds between successive probes once idle has fired
  count   number of unacknowledged probes before the connection is dropped

Every mainstream OS exposes keepalive knobs, but the option numbers, units,
and semantics differ:

  Linux   SO_KEEPALIVE / TCP_KEEPIDLE (s) / TCP_KEEPINTVL (s) / TCP_KEEPCNT
  macOS   SO_KEEPALIVE / TCP_KEEPALIVE (s) / TCP_KEEPINTVL (s) / TCP_KEEPCNT
  Windows SO_KEEPALIVE + a single tcp_keepalive struct whose onoff, time (ms),
          interval (ms), and count (probes) are set in one ioctl.

Windows only gained per-socket control over count via SIO_KEEPALIVE_VALS on
Vista; prior to that the system default was fixed. We do not try to detect
the OS version at runtime -- doing so from pure Python is fragile and the
result is platform-specific anyway. Instead we ask the caller to name the
platform, validate that it is one we know, and raise ValueError otherwise.
This is the deliberate trade-off: a small, testable, dependency-free function
rather than a runtime probe that can lie.

Edge cases the code handles explicitly:
  * Non-positive idle/interval/count are rejected before any platform math.
  * Windows expects milliseconds; the seconds we accept are converted and
    capped at the 32-bit unsigned range used by the Win32 keepalive struct.
    A value that fits in seconds can overflow once multiplied by 1000, so we
    cap rather than let a silent wrap produce nonsense.
  * Linux and macOS expose the values directly in seconds, so they pass
    through unchanged after validation.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Dict, Any


# Win32 tcp_keepalive (and SIO_KEEPALIVE_VALS) uses 32-bit unsigned fields for
# the millisecond timers. Anything larger would wrap silently, so we clamp.
_WINDOWS_MAX_MS = 0xFFFFFFFF


@dataclass(frozen=True)
class KeepaliveOptions:
    """A platform-specific bundle of socket option values.

    Attributes:
        enable: value to pass to setsockopt for the master on/off flag.
        options: ordered mapping of (level, optname) -> value, ready to iterate
            in setsockopt calls. The level/optname pairs are plain integers so
            callers can bind them against socket.SOL_SOCKET / socket.IPPROTO_TCP
            without importing this library's own constants.

    The mapping is ordered by the order the caller should apply the options:
    the master enable flag first, then the timing knobs. Applying the master
    flag last can, on some stacks, briefly leave a socket with default timing
    and keepalive enabled, which is exactly the surprise this library exists
    to avoid.
    """

    enable: Any
    options: Dict[tuple, Any] = field(default_factory=dict)

    def to_setsockopt_pairs(self):
        """Yield (level, optname, value) triples in application order.

        Convenience for callers who want a flat sequence rather than a dict;
        the dict itself is already ordered, but some style guides prefer an
        explicit iterable of triples.
        """
        for (level, optname), value in self.options.items():
            yield (level, optname, value)


def _validate(idle: float, interval: float, count: int) -> None:
    """Reject values that cannot produce a working keepalive configuration.

    Keepalive semantics require positive timers and at least one probe; zero
    or negative values are not "disable" signals here (disabling is done by
    not calling this function at all), so we fail loudly rather than guess.
    """
    if idle <= 0:
        raise ValueError(f"idle must be positive, got {idle!r}")
    if interval <= 0:
        raise ValueError(f"interval must be positive, got {interval!r}")
    if count <= 0:
        raise ValueError(f"count must be a positive integer, got {count!r}")


def _clamp_ms(seconds: float) -> int:
    """Convert seconds to an int number of milliseconds, capped at 2^32-1.

    Rounding down is safe here: a sub-millisecond difference in a keepalive
    timer has no practical meaning, and the underlying Win32 struct cannot
    represent fractions anyway. Capping prevents a silent 32-bit wrap that
    would turn "one billion seconds" into a few seconds.
    """
    ms = int(seconds * 1000)
    if ms < 0:
        # Defensive: int() floors, so a tiny negative input could slip past
        # _validate if a caller passed -0.0; keep the guard local.
        raise ValueError(f"negative millisecond result from {seconds!r}")
    if ms > _WINDOWS_MAX_MS:
        return _WINDOWS_MAX_MS
    return ms


def _linux(idle: float, interval: float, count: int) -> KeepaliveOptions:
    # Level/optname constants are not imported from the socket module here so
    # that this module stays importable in environments where socket is a stub
    # (e.g. some restrictive type-checking sandboxes). The numeric values are
    # ABI-stable on Linux.
    SOL_SOCKET = 0xFFFF
    IPPROTO_TCP = 6
    SO_KEEPALIVE = 0x0009
    TCP_KEEPIDLE = 4
    TCP_KEEPINTVL = 5
    TCP_KEEPCNT = 6
    return KeepaliveOptions(
        enable=1,
        options={
            (SOL_SOCKET, SO_KEEPALIVE): 1,
            (IPPROTO_TCP, TCP_KEEPIDLE): int(idle),
            (IPPROTO_TCP, TCP_KEEPINTVL): int(interval),
            (IPPROTO_TCP, TCP_KEEPCNT): int(count),
        },
    )


def _macos(idle: float, interval: float, count: int) -> KeepaliveOptions:
    SOL_SOCKET = 0xFFFF
    IPPROTO_TCP = 6
    SO_KEEPALIVE = 0x0008
    TCP_KEEPALIVE = 0x10
    TCP_KEEPINTVL = 0x101
    TCP_KEEPCNT = 0x102
    return KeepaliveOptions(
        enable=1,
        options={
            (SOL_SOCKET, SO_KEEPALIVE): 1,
            (IPPROTO_TCP, TCP_KEEPALIVE): int(idle),
            (IPPROTO_TCP, TCP_KEEPINTVL): int(interval),
            (IPPROTO_TCP, TCP_KEEPCNT): int(count),
        },
    )


def _windows(idle: float, interval: float, count: int) -> KeepaliveOptions:
    # Windows does not expose separate per-knob socket options. Instead a
    # single SIO_KEEPALIVE_VALS ioctl takes a struct with onoff, time (ms),
    # interval (ms), and count. We represent the whole struct as a tuple so
    # the caller can pack it with struct.pack("llll", *values) without us
    # importing struct here (keeps the module dependency-free at import time
    # and lets the caller choose their own struct layout if they prefer).
    SOL_SOCKET = 0xFFFF
    # SIO_KEEPALIVE_VALS ioctl code, computed the way Win32 defines it:
    # IOC_IN (0x80000000) | IOC_VENDOR (0x18000000) | 4. Stored as a plain
    # int because socket.ioctl expects the numeric code.
    SIO_KEEPALIVE_VALS = 0x98000004
    return KeepaliveOptions(
        enable=1,
        options={
            (SOL_SOCKET, SIO_KEEPALIVE_VALS): (
                1,
                _clamp_ms(idle),
                _clamp_ms(interval),
                int(count),
            ),
        },
    )


_PLATFORMS = {
    "linux": _linux,
    "macos": _macos,
    "windows": _windows,
}


def compute_keepalive(platform: str, idle: float, interval: float, count: int) -> KeepaliveOptions:
    """Return platform-specific keepalive option values for the given target.

    Args:
        platform: one of "linux", "macos", "windows".
        idle: seconds of silence before the first probe (must be > 0).
        interval: seconds between probes (must be > 0).
        count: number of unacknowledged probes before the connection is dropped
            (must be a positive integer).

    Returns:
        A KeepaliveOptions whose `options` mapping is ordered for application:
        master enable flag first, then timing knobs.

    Raises:
        ValueError: if `platform` is unknown or any timing value is non-positive.

    The function is pure: it performs no I/O and touches no sockets. That is the
    point -- it exists so callers can unit-test their keepalive setup without
    creating real sockets.
    """
    key = platform.lower()
    if key not in _PLATFORMS:
        raise ValueError(
            f"unsupported platform {platform!r}; expected one of {sorted(_PLATFORMS)}"
        )
    _validate(idle, interval, count)
    return _PLATFORMS[key](idle, interval, count)
