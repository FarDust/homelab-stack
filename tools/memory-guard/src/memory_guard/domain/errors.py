"""Typed failures; every one maps to a nonzero exit with a diagnostic on stderr."""


class GuardError(Exception):
    """Base class."""


class ProbeError(GuardError):
    """A required counter could not be read."""


class StateError(GuardError):
    """The state file is unreadable, malformed or not writable."""


class AlertError(GuardError):
    """The alert path did not confirm delivery."""


class ReclaimError(GuardError):
    """The opt-in WSL cache drop failed, timed out or could not be verified."""


class PublishError(GuardError):
    """The commit-headroom textfile could not be written into the WSL guest."""
