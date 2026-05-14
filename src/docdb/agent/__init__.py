"""Level-3 search agent.

The toolbox exposes Direct API + Text2SQL primitives to a tool-calling
LLM. The loop runs the LLM until it stops invoking tools, then bundles
the answer + cited document IDs into an AgentResult.
"""

from docdb.agent.toolbox import ToolInvocation, ToolSpec, Toolbox

__all__ = ["ToolInvocation", "ToolSpec", "Toolbox"]
