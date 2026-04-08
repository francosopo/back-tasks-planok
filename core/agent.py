import os
from typing import Any, Dict, List, Optional

from dotenv import load_dotenv


def _ensure_django() -> None:
    """
    Allows calling these tools from scripts/REPL without requiring the caller
    to have already initialized Django.
    """
    if os.environ.get("DJANGO_SETTINGS_MODULE") is None:
        os.environ["DJANGO_SETTINGS_MODULE"] = "task_manager.settings"

    try:
        import django  # type: ignore
    except Exception as e:  # pragma: no cover
        raise RuntimeError(
            "Django is required to use core.agent tools. "
            "Install dependencies and run inside the project venv."
        ) from e

    # Idempotent: safe to call multiple times.
    django.setup()


load_dotenv()


def _get_llm():
    """
    Uses credentials from .env (e.g. OPENAI_API_KEY).
    """
    try:
        from langchain_openai import ChatOpenAI  # type: ignore
    except Exception as e:  # pragma: no cover
        raise RuntimeError(
            "Missing LangChain OpenAI integration. Install `langchain-openai`."
        ) from e

    # Accept a few common env var names to reduce friction.
    api_key = (
        os.getenv("OPENAI_API_KEY")
        or os.getenv("LANGCHAIN_API_KEY")
        or os.getenv("API_KEY")
    )
    organization = (
        os.getenv("OPENAI_ORGANIZATION")
        or os.getenv("OPENAI_ORG")
        or os.getenv("ORGANIZATION")
    )

    if not api_key:
        raise RuntimeError(
            "Missing API key in .env. Set OPENAI_API_KEY (recommended) "
            "or LANGCHAIN_API_KEY/API_KEY."
        )

    model = os.getenv("OPENAI_MODEL", "gpt-4o-mini")
    temperature = float(os.getenv("OPENAI_TEMPERATURE", "0.2"))
    return ChatOpenAI(
        model=model,
        temperature=temperature,
        api_key=api_key,
        organization=organization,
    )


def _get_task(task_id: int):
    _ensure_django()
    from core.models import Task  # local import after django.setup()

    return Task.objects.get(pk=task_id)


def split_task(task_id: int) -> Dict[str, Any]:
    """
    Read a Task instance and propose subtasks that help achieve the main goal.
    """
    task = _get_task(task_id)
    llm = _get_llm()

    prompt = (
        "You help break a task into small actionable subtasks.\n\n"
        f"Task title: {task.title}\n"
        f"Task description: {task.description or ''}\n\n"
        "Return JSON with this exact schema:\n"
        "{\n"
        '  "subtasks": [\n'
        "    {\n"
        '      "title": string,\n'
        '      "description": string\n'
        "    }\n"
        "  ]\n"
        "}\n"
        "Constraints:\n"
        "- 3 to 8 subtasks\n"
        "- Each title <= 80 chars\n"
        "- Each description <= 240 chars\n"
        "- Subtasks must clearly contribute to the main goal\n"
        "- Output must be valid JSON only\n"
    )

    content = llm.invoke(prompt).content
    if isinstance(content, list):
        # Some providers return content parts; join text parts.
        content = "\n".join([str(x) for x in content])

    import json

    return json.loads(str(content))


def classify_task(task_id: int) -> Dict[str, Any]:
    """
    Read a Task instance and suggest a priority classification.
    """
    task = _get_task(task_id)
    llm = _get_llm()

    from core.models import Task as TaskModel  # after setup

    choices = [c[0] for c in TaskModel.Priority.choices]

    prompt = (
        "Classify the task priority.\n\n"
        f"Task title: {task.title}\n"
        f"Task description: {task.description or ''}\n\n"
        f"Allowed priorities: {choices}\n\n"
        "Return JSON with this exact schema:\n"
        "{\n"
        '  "priority": one of the allowed priorities,\n'
        '  "reason": string (<= 200 chars)\n'
        "}\n"
        "Output must be valid JSON only.\n"
    )

    content = llm.invoke(prompt).content
    if isinstance(content, list):
        content = "\n".join([str(x) for x in content])

    import json

    data = json.loads(str(content))
    if data.get("priority") not in choices:
        raise ValueError(f"Model returned invalid priority: {data.get('priority')}")
    return data


def _load_tool_calling_agent_stack():
    """
    LangChain v1+ moved AgentExecutor / create_tool_calling_agent to
    ``langchain_classic``. Older releases expose them under ``langchain.agents``.
    """
    try:
        from langchain.agents import AgentExecutor, create_tool_calling_agent  # type: ignore

        return AgentExecutor, create_tool_calling_agent
    except ImportError:
        pass
    try:
        from langchain_classic.agents import (  # type: ignore
            AgentExecutor,
            create_tool_calling_agent,
        )

        return AgentExecutor, create_tool_calling_agent
    except ImportError as e:
        raise RuntimeError(
            "Could not import AgentExecutor / create_tool_calling_agent. "
            "Install `langchain-classic` (LangChain v1+) or use LangChain 0.x "
            "where these live in `langchain.agents`."
        ) from e


def build_agent():
    """
    Returns an AgentExecutor wired with the tools in this module.
    """
    try:
        from langchain_core.prompts import (  # type: ignore
            ChatPromptTemplate,
            MessagesPlaceholder,
        )
        from langchain_core.tools import tool  # type: ignore
    except Exception as e:  # pragma: no cover
        raise RuntimeError(
            "Missing langchain-core. Install `langchain` or `langchain-core`."
        ) from e

    AgentExecutor, create_tool_calling_agent = _load_tool_calling_agent_stack()

    llm = _get_llm()

    @tool
    def split_task_tool(task_id: int) -> Dict[str, Any]:
        """Suggest subtasks for the given Task id."""
        return split_task(task_id)

    @tool
    def classify_task_tool(task_id: int) -> Dict[str, Any]:
        """Suggest priority classification for the given Task id."""
        return classify_task(task_id)

    tools = [split_task_tool, classify_task_tool]

    prompt = ChatPromptTemplate.from_messages(
        [
            (
                "system",
                "You are a helpful task assistant for a Django Task model. "
                "Use the provided tools when asked to split or classify tasks. "
                "Be concise and return structured outputs from tools as-is.",
            ),
            ("human", "{input}"),
            # Required by create_tool_calling_agent / AgentExecutor for tool round-trips.
            MessagesPlaceholder(variable_name="agent_scratchpad"),
        ]
    )

    agent = create_tool_calling_agent(llm, tools, prompt)
    return AgentExecutor(agent=agent, tools=tools, verbose=False)
