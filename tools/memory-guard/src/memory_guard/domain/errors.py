"""Typed failures; every one maps to a nonzero exit with a diagnostic on stderr."""


class GuardError(Exception):
    """Base class."""


class ProbeError(GuardError):
    """A required counter could not be read."""


class StateError(GuardError):
    """The state file is unreadable, malformed or not writable."""


class AlertError(GuardError):
    """The alert path did not confirm delivery."""
