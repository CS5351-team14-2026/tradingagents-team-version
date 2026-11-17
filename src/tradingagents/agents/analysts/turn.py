"""One turn of a tool-using analyst, and its last turn once its tool rounds are spent."""

import json

from langchain_core.messages import AIMessage, HumanMessage, ToolMessage

from tradingagents.llm_clients.invocation import CallSpec, invoke_with_budget
from tradingagents.run_budget import CallRole

WRAP_UP = (
    "You have used every tool round this report allows. Write your final report "
    "now from the tool results above, and say which data you could not retrieve."
)
BUDGET_WRAP_UP = (
    "The token budget stopped another optional tool-follow-up call. Write your "
    "final report now using only the tool results already collected above, "
    "and clearly state which evidence could not be collected."
)


def take_turn(prompt, llm, tools, messages, *, phase="analyst"):
    """The analyst's reply and its report, which stays empty while it calls tools.

    Told to wrap up, it answers without tools: a model offered tools may call one
    whatever it is told. Its earlier calls and their results reach it as text,
    since a provider may refuse a history holding tool calls when none are bound.
    """
    wrap_up = (
        messages and isinstance(messages[-1], HumanMessage)
        and messages[-1].content in (WRAP_UP, BUDGET_WRAP_UP)
    )
    if wrap_up:
        # The prompt lists the tools it offers; a model told of tools it cannot
        # call may still try, and some providers then answer with nothing.
        tool_names = (
            "none; the token budget stopped optional follow-up calls"
            if messages[-1].content == BUDGET_WRAP_UP
            else "none; your tool rounds are spent"
        )
        prompt = prompt.partial(tool_names=tool_names)
        formatted = prompt.format_messages(messages=_as_text(messages))
        result = invoke_with_budget(
            llm,
            formatted,
            call=CallSpec(phase=f"{phase}.wrap_up", role=CallRole.REQUIRED),
        )
        return result, result.content
    # Formatting first keeps the admission ID attached to the actual model
    # request instead of an enclosing RunnableSequence (REQ-TA-FR-002).
    formatted = prompt.format_messages(messages=messages)
    role = CallRole.OPTIONAL if any(isinstance(message, ToolMessage) for message in messages) else CallRole.REQUIRED
    result = invoke_with_budget(
        llm.bind_tools(tools),
        formatted,
        call=CallSpec(phase=phase, role=role),
    )
    return result, "" if result.tool_calls else result.content


def _as_text(messages):
    """The history with its tool calls and tool results written out as plain messages."""
    written = []
    for message in messages:
        if isinstance(message, AIMessage) and message.tool_calls:
            said = message.content if isinstance(message.content, str) else ""
            calls = "; ".join(f"{c['name']}({json.dumps(c['args'], default=str)})" for c in message.tool_calls)
            written.append(AIMessage(content=f"{said}\n[Called {calls}]".strip()))
        elif isinstance(message, ToolMessage):
            written.append(HumanMessage(content=f"[{message.name or 'Tool'} returned]\n{message.content}"))
        else:
            written.append(message)
    return written
