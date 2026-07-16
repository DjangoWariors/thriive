"""Subject adapter contract + registry.

A domain app (incentives, …) registers one adapter per ``subject_type`` so the generic
engine can: find the routing anchor, snapshot context, render an inbox summary, and apply
the terminal decision back onto the domain object — all without the engine importing the
domain app. Registration happens in the domain ``AppConfig.ready()``.
"""
from abc import ABC, abstractmethod

_REGISTRY: dict[str, "SubjectAdapter"] = {}


class SubjectAdapter(ABC):
    """Bridge between a domain object and the workflow engine."""

    #: dotted model label, e.g. 'incentives.PayoutException'
    subject_type: str = ''

    @abstractmethod
    def load(self, subject_id: int):
        """Return the domain object for ``subject_id`` (or None if gone)."""

    @abstractmethod
    def anchor_entity(self, subject):
        """Node the approval routes from (managers above it approve). May be None."""

    @abstractmethod
    def build_context(self, subject) -> dict:
        """Frozen snapshot for conditional routing + display."""

    def summary(self, subject) -> dict:
        """Compact dict for inbox cards / detail headers."""
        return {}

    def on_approved(self, instance, subject) -> None:
        """Apply the terminal-approved decision onto the domain object."""

    def on_rejected(self, instance, subject) -> None:
        """Apply the terminal-rejected decision onto the domain object."""


def register(subject_type: str, adapter: SubjectAdapter) -> None:
    _REGISTRY[subject_type] = adapter


def get(subject_type: str) -> SubjectAdapter | None:
    return _REGISTRY.get(subject_type)


def is_registered(subject_type: str) -> bool:
    return subject_type in _REGISTRY
