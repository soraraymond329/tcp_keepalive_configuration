# tcp_keepalive_configuration

Calculates per-socket TCP keepalive option values from a desired idle/interval/count specification across Linux, macOS, and Windows option sets. Pure standard library, no network access, no sockets touched.

## Usage

```python
from tcp_keepalive_configuration import compute_keepalive, KeepaliveOptions

opts: KeepaliveOptions = compute_keepalive("linux", idle=30, interval=10, count=3)

# opts.options is an ordered mapping of (level, optname) -> value,
# master enable flag first, then timing knobs.
```

For Windows, the single `(SOL_SOCKET, SIO_KEEPALIVE_VALS)` entry's value is a `(onoff, idle_ms, interval_ms, count)` tuple suitable for `struct.pack("llll", *value)`.

## Why this exists

Configuring TCP keepalive means mapping three human-scale numbers (idle seconds, interval seconds, probe count) onto platform-specific socket options whose names, units, and shapes all differ. Linux uses seconds across three `IPPROTO_TCP` options. macOS uses seconds but with a different idle option name. Windows stuffs everything into one ioctl that wants milliseconds. Doing this ad hoc per call site is where off-by-1000 bugs and wrong option constants live.

The trade-off: this library does not probe the running OS. You tell it the platform. A runtime probe from pure Python is fragile and the result is platform-specific anyway, so a small explicit function beats a clever one that can lie.

## Edge you will hit

Windows' keepalive struct uses 32-bit unsigned millisecond fields. An `idle` value that is perfectly reasonable in seconds can overflow once multiplied by 1000. The library caps at `0xFFFFFFFF` rather than letting the value wrap silently. If you pass something absurd like five million seconds, you will get the cap, not an error. Also, fractional seconds are truncated toward zero on every platform, not rounded.
