"""MatCreator agent sub-package.

Exports ``thinking_agent``, the single LlmAgent that handles planning and
execution in one conversational loop.
"""

from .agent import thinking_agent

__all__ = ["thinking_agent"]
