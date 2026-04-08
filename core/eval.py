"""
Lightweight, local evaluation for `core.agent` tools.

Goal:
- Exercise the tool functions (`split_task`, `classify_task`) against a real
  Django `Task` row without requiring OpenAI or LangChain installs.

Usage:
  From the project root (directory that contains ``manage.py``):

pyt  python -m core.eval
  python core/eval.py
"""

from __future__ import annotations

import json
import os
import sys
from dataclasses import dataclass

# Django loads ``INSTALLED_APPS`` as top-level packages (e.g. ``core``). If this
# file is run as ``python core/eval.py``, Python puts ``.../core`` on ``sys.path``
# first, so ``import core`` fails. Always ensure the project root is first.
_PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _PROJECT_ROOT not in sys.path:
    sys.path.insert(0, _PROJECT_ROOT)
from types import ModuleType
from typing import Any, Dict, List, Optional, Tuple


@dataclass(frozen=True)
class EvalResult:
    name: str
    ok: bool
    details: str = ""


def _install_ephemeral_django_settings() -> str:
    """
    Create an in-memory settings module for eval runs.

    By default it mirrors the Postgres credentials in `task_manager/settings.py`.
    You can override connection values with env vars:

    - EVAL_DB_NAME (default: tasks)
    - EVAL_DB_USER (default: planok)
    - EVAL_DB_PASSWORD (default: planok)
    - EVAL_DB_HOST (default: db)
    - EVAL_DB_PORT (default: 5432)
    """
    module_name = "core._eval_settings"
    mod = ModuleType(module_name)

    # Minimal Django settings to load the core app + model.
    mod.SECRET_KEY = "eval-secret-key"
    mod.DEBUG = False
    mod.USE_TZ = True
    mod.TIME_ZONE = "UTC"
    mod.ALLOWED_HOSTS = ["*"]

    mod.INSTALLED_APPS = [
        "django.contrib.auth",
        "django.contrib.contenttypes",
        "django.contrib.sessions",
        "django.contrib.messages",
        "django.contrib.staticfiles",
        "core",
    ]

    mod.MIDDLEWARE = [
        "django.middleware.security.SecurityMiddleware",
        "django.contrib.sessions.middleware.SessionMiddleware",
        "django.middleware.common.CommonMiddleware",
        "django.middleware.csrf.CsrfViewMiddleware",
        "django.contrib.auth.middleware.AuthenticationMiddleware",
        "django.contrib.messages.middleware.MessageMiddleware",
    ]

    mod.ROOT_URLCONF = "task_manager.urls"

    db_name = os.getenv("EVAL_DB_NAME", "tasks_bd")
    db_user = os.getenv("EVAL_DB_USER", "postgres")
    db_password = os.getenv("EVAL_DB_PASSWORD", "postgres")
    db_host = os.getenv("EVAL_DB_HOST", "db")
    db_port = os.getenv("EVAL_DB_PORT", "5432")

    mod.DATABASES = {
        "default": {
            "ENGINE": "django.db.backends.postgresql",
            "NAME": db_name,
            "USER": db_user,
            "PASSWORD": db_password,
            "HOST": db_host,
            "PORT": db_port,
        }
    }

    mod.DEFAULT_AUTO_FIELD = "django.db.models.AutoField"

    sys.modules[module_name] = mod
    os.environ["DJANGO_SETTINGS_MODULE"] = module_name
    return module_name


def _django_setup_and_syncdb() -> None:
    import django  # type: ignore
    from django.core.management import call_command  # type: ignore

    django.setup()
    # `run_syncdb=True` creates tables for apps without migrations.
    call_command("migrate", run_syncdb=True, interactive=False, verbosity=0)


class _StubLLMResponse:
    def __init__(self, content: str):
        self.content = content


class _StubLLM:
    """
    Deterministic stub for the LLM used by core.agent._get_llm().
    It detects which tool prompt is being used and returns valid JSON.

    ``create_tool_calling_agent`` / ``build_agent`` require ``bind_tools`` on the
    chat model; the real ``ChatOpenAI`` implements it. This stub adds a minimal
    implementation so the agent graph can be built in eval without a live API.
    """

    def bind_tools(self, tools, **kwargs):  # noqa: ANN001, D401
        """Return self; eval only checks that ``build_agent()`` constructs."""
        return self

    def __call__(self, *args, **kwargs):  # noqa: ANN001
        """
        Make the stub acceptable to LangChain codepaths that accept a callable.
        We route calls to ``invoke`` using the first positional arg as the prompt.
        """
        prompt = args[0] if args else kwargs.get("prompt", "")
        return self.invoke(prompt)

    def invoke(self, prompt: str) -> _StubLLMResponse:  # noqa: D401
        if "break a task into small actionable subtasks" in prompt:
            payload = {
                "subtasks": [
                    {"title": "Define acceptance criteria", "description": "Write clear success criteria."},
                    {"title": "Implement API endpoint", "description": "Add endpoint logic and validations."},
                    {"title": "Add tests", "description": "Cover happy path and error cases."},
                ]
            }
            return _StubLLMResponse(json.dumps(payload))

        if "Classify the task priority" in prompt:
            # core.models.Task.Priority choices are: low, medium, high, urgent
            payload = {"priority": "high", "reason": "User-visible work with clear deadline impact."}
            return _StubLLMResponse(json.dumps(payload))

        return _StubLLMResponse(json.dumps({"error": "Unexpected prompt"}))


def _patch_agent_llm() -> None:
    """
    Replace core.agent._get_llm() with a stub so eval is offline and repeatable.
    """
    from core import agent as agent_mod

    agent_mod._get_llm = lambda: _StubLLM()  # type: ignore[attr-defined]


def _assert(condition: bool, message: str) -> Tuple[bool, str]:
    return (True, "") if condition else (False, message)


def _eval_split_task() -> EvalResult:
    from core.models import Task
    from core.agent import split_task

    t = Task.objects.create(title="Ship v1 onboarding", description="Implement onboarding flow.", status=Task.Status.PENDING)
    data = split_task(t.id)

    ok, msg = _assert(isinstance(data, dict), f"Expected dict, got {type(data)}")
    if not ok:
        return EvalResult("split_task returns dict", False, msg)

    subtasks = data.get("subtasks")
    ok, msg = _assert(isinstance(subtasks, list) and len(subtasks) >= 3, "Expected >=3 subtasks list")
    if not ok:
        return EvalResult("split_task returns subtasks", False, msg)

    for i, st in enumerate(subtasks):
        ok, msg = _assert(isinstance(st, dict), f"Subtask[{i}] not a dict")
        if not ok:
            return EvalResult("split_task subtask shape", False, msg)
        ok, msg = _assert(bool(str(st.get("title") or "").strip()), f"Subtask[{i}] missing title")
        if not ok:
            return EvalResult("split_task subtask title", False, msg)
        ok, msg = _assert("description" in st, f"Subtask[{i}] missing description")
        if not ok:
            return EvalResult("split_task subtask description", False, msg)

    return EvalResult("split_task", True)


def _eval_classify_task() -> EvalResult:
    from core.models import Task
    from core.agent import classify_task

    t = Task.objects.create(title="Fix failing deploy", description="Production deploy is failing in CI.", status=Task.Status.PENDING)
    data = classify_task(t.id)

    ok, msg = _assert(isinstance(data, dict), f"Expected dict, got {type(data)}")
    if not ok:
        return EvalResult("classify_task returns dict", False, msg)

    ok, msg = _assert(data.get("priority") in [c[0] for c in Task.Priority.choices], "Invalid priority value")
    if not ok:
        return EvalResult("classify_task priority valid", False, msg)

    ok, msg = _assert(isinstance(data.get("reason"), str) and len(data["reason"]) <= 200, "Invalid reason")
    if not ok:
        return EvalResult("classify_task reason valid", False, msg)

    return EvalResult("classify_task", True)


def _eval_build_agent_optional() -> EvalResult:
    """
    `build_agent()` depends on LangChain packages not present in this repo's
    requirements.txt. We treat absence as a SKIP, not a failure.
    """
    try:
        from core.agent import build_agent
    except Exception as e:  # pragma: no cover
        return EvalResult("build_agent import", False, str(e))

    try:
        _ = build_agent()
        return EvalResult("build_agent", True)
    except RuntimeError as e:
        # Expected in minimal installs.
        return EvalResult("build_agent (optional)", True, f"SKIP: {e}")
    except Exception as e:
        return EvalResult("build_agent (optional)", False, f"Unexpected error: {e}")


def run() -> List[EvalResult]:
    _install_ephemeral_django_settings()
    _django_setup_and_syncdb()
    _patch_agent_llm()

    results: List[EvalResult] = []
    results.append(_eval_split_task())
    results.append(_eval_classify_task())
    results.append(_eval_build_agent_optional())
    return results


def _print_results(results: List[EvalResult]) -> int:
    failed = [r for r in results if not r.ok]
    for r in results:
        status = "PASS" if r.ok else "FAIL"
        line = f"{status} - {r.name}"
        if r.details:
            line += f" :: {r.details}"
        print(line)
    return 0 if not failed else 1


if __name__ == "__main__":
    sys.exit(_print_results(run()))

