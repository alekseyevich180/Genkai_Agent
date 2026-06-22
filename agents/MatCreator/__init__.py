"""MatCreator agent package.

Exports the ADK ``App`` instance (``app``) that wires together the root
orchestration agent, thinking/execution sub-agents, and the session
resumability / compaction configuration.
"""

from .agent import app  # noqa: F401
__all__ = ["app"]