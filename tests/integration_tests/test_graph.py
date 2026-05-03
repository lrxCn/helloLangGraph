import pytest
from langgraph.pregel import Pregel

from agent.graph import agent

pytestmark = pytest.mark.anyio


async def test_agent_graph_is_compiled() -> None:
    assert isinstance(agent, Pregel)
