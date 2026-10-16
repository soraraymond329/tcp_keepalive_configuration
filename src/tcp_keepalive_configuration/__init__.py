# Public surface for tcp_keepalive_configuration.
#
# We export only the two symbols callers actually need: the dataclass that
# bundles a computed option set, and the function that performs the
# computation. Keeping the surface tiny makes it obvious which names are
# stable across releases.

from .core import KeepaliveOptions, compute_keepalive

__all__ = ["KeepaliveOptions", "compute_keepalive"]
