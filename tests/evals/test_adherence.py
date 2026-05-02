"""Agentic evaluation tests for TurnZero prior injection and adherence.

Unit tests (always run — no LLM or Ollama required):
  test_environment_structure              – EvalEnvironment creates correct dirs
  test_add_block_creates_yaml             – add_block writes valid YAML
  test_direct_bridge_inject_known_block   – inject_block returns constraint text
  test_simulated_agent_tool_call_order    – list called before inject
  test_simulated_agent_returns_text       – SimulatedAgent returns non-empty text
  test_injected_text_contains_constraint  – custom constraint propagates to injection
  test_submit_candidate_raw_saves_file    – submit_candidate_raw creates YAML file

Eval tests (set TURNZERO_RUN_EVALS=1 to run — require Ollama or real CLIs):
  test_ollama_quirk_adherence             – Ollama uses project-specific naming from prior
  test_ollama_learning_sensitivity        – Ollama calls submit_candidate on "remember this"
  test_gemini_cli_instruction_adherence   – Gemini CLI follows rule baked into GEMINI.md
  test_claude_cli_instruction_adherence   – Claude Code CLI follows rule baked into CLAUDE.md
  test_codex_cli_instruction_adherence    – Codex CLI follows rule baked into AGENTS.md
"""

from __future__ import annotations

import os

import pytest
import yaml

from .runner import (
    DirectBridge,
    EvalEnvironment,
    OllamaAgent,
    RealCLIProjectAgent,
    SimulatedAgent,
)

RUN_EVALS = os.environ.get("TURNZERO_RUN_EVALS", "0").lower() in ("1", "true", "yes")
evals_only = pytest.mark.skipif(
    not RUN_EVALS,
    reason="Set TURNZERO_RUN_EVALS=1 to run agentic evals (requires Ollama or real CLIs)",
)

# ---------------------------------------------------------------------------
# Unit tests — always run, no LLM required
# ---------------------------------------------------------------------------


def test_environment_structure() -> None:
    with EvalEnvironment() as env:
        assert env.data_dir.exists()
        assert env.project_dir.exists()
        for tier in ["personal", "local", "community", "candidates"]:
            assert (env.blocks_dir / tier).exists(), f"missing tier dir: {tier}"
        assert (env.project_dir / "CLAUDE.md").exists()
        assert (env.project_dir / "GEMINI.md").exists()
        assert (env.project_dir / "AGENTS.md").exists()


def test_add_block_creates_yaml() -> None:
    constraint = "Always name the primary database connection variable `vault_conn`."
    with EvalEnvironment() as env:
        env.add_block(
            slug="eval-db-naming",
            tier="local",
            constraints=[constraint],
            domain="fastapi",
            intent="build",
        )
        block_path = env.blocks_dir / "local" / "eval-db-naming.yaml"
        assert block_path.exists()
        data = yaml.safe_load(block_path.read_text())
        assert data["slug"] == "eval-db-naming"
        assert constraint in data["constraints"]
        assert data["domain"] == "fastapi"


def test_direct_bridge_inject_known_block() -> None:
    """inject_block on a bundled community block returns its constraint text.

    Uses the bundled index fallback — no index build needed.
    """
    with EvalEnvironment() as env:
        bridge = DirectBridge(env)
        text = bridge.inject_block("nextjs15-approuter-build")
        assert len(text) > 50
        assert "next" in text.lower() or "Next" in text


def test_simulated_agent_tool_call_order() -> None:
    """list_suggested_blocks is called first, then inject_block for each result."""
    with EvalEnvironment() as env:
        bridge = DirectBridge(env)
        agent = SimulatedAgent(bridge)
        agent.chat("build a Next.js app with Supabase authentication")

        assert agent.tool_calls, "no tool calls recorded"
        assert agent.tool_calls[0] == "list_suggested_blocks"
        inject_calls = [c for c in agent.tool_calls if c.startswith("inject_block:")]
        assert inject_calls, "no inject_block calls made"


def test_simulated_agent_returns_text() -> None:
    """SimulatedAgent returns non-empty injection text for a real prompt."""
    with EvalEnvironment() as env:
        bridge = DirectBridge(env)
        agent = SimulatedAgent(bridge)
        result = agent.chat("build a Next.js app with Supabase authentication")
        assert len(result) > 100, f"injection text too short: {len(result)} chars"


def test_injected_text_contains_constraint() -> None:
    """A constraint added via add_block propagates into SimulatedAgent's injection.

    This is the core retrieval-to-injection pipeline test:
    add block → build index → retrieve → inject → constraint text present.
    """
    constraint = "Always name the primary database connection variable `vault_conn`."
    with EvalEnvironment() as env:
        env.add_block(
            slug="eval-db-naming",
            tier="local",
            constraints=[constraint],
            domain="fastapi",
            intent="build",
        )
        bridge = DirectBridge(env)
        agent = SimulatedAgent(bridge)
        result = agent.chat(
            "I am building a FastAPI app with PostgreSQL. "
            "How do I set up the database connection?"
        )

        assert "vault_conn" in result, (
            f"Constraint keyword 'vault_conn' not found in injected text.\n"
            f"Injected blocks: {agent.injected_blocks}\n"
            f"Result (first 800 chars):\n{result[:800]}"
        )


def test_submit_candidate_raw_saves_file() -> None:
    """submit_candidate_raw writes a YAML file to candidates/."""
    with EvalEnvironment() as env:
        bridge = DirectBridge(env)
        path = bridge.submit_candidate_raw(
            block_id="my-test-rule",
            content="slug: my-test-rule\nconstraints:\n- Always use snake_case.\n",
        )
        assert path.exists()
        assert path.stem == "my-test-rule"
        data = yaml.safe_load(path.read_text())
        assert data["slug"] == "my-test-rule"


# ---------------------------------------------------------------------------
# Eval tests — require TURNZERO_RUN_EVALS=1
# ---------------------------------------------------------------------------


@evals_only
@pytest.mark.evals
def test_ollama_quirk_adherence() -> None:
    """Ollama adopts a project-specific naming convention injected via Expert Prior.

    What this proves: when a constraint is in the index, the agent retrieves it,
    reads it via inject_block, and applies it to the generated code.
    """
    constraint = (
        "PROJECT RULE: Always name the primary PostgreSQL connection variable `vault_conn`. "
        "Reference the database as 'the vault' in all code comments and docstrings."
    )
    with EvalEnvironment() as env:
        env.add_block(
            slug="project-db-naming-convention",
            tier="local",
            constraints=[constraint],
            domain="postgresql",
            intent="build",
        )
        agent = OllamaAgent(env)
        response = agent.chat(
            "Write a Python function `get_db_connection()` that opens and returns "
            "a PostgreSQL connection. Use the naming conventions from our project's Expert Priors."
        )

    assert "vault_conn" in response or "vault" in response.lower(), (
        f"Expected 'vault_conn' or 'vault' in response.\n"
        f"Tool calls made: {agent.tool_calls_made}\n"
        f"Response:\n{response[:1500]}"
    )
    assert "list_suggested_blocks" in agent.tool_calls_made, (
        "Agent never called list_suggested_blocks — prior injection didn't happen."
    )


@evals_only
@pytest.mark.evals
def test_ollama_learning_sensitivity() -> None:
    """Ollama calls submit_candidate when the user explicitly asks to save a rule.

    What this proves: the agent recognises 'remember this' intent and triggers
    the learning tool rather than just acknowledging verbally.
    """
    with EvalEnvironment() as env:
        agent = OllamaAgent(env)
        agent.chat(
            "New project rule that you must save for future sessions: "
            "Every Python function in this project must include a docstring "
            "that ends with the token 'VERIFIED'. "
            "Please remember and save this rule now."
        )

        assert "submit_candidate" in agent.tool_calls_made, (
            f"Expected submit_candidate to be called.\n"
            f"Tool calls made: {agent.tool_calls_made}"
        )

        candidates = list((env.data_dir / "candidates").glob("*.yaml"))
        personal = [
            f
            for f in (env.blocks_dir / "personal").glob("*.yaml")
            if f.stem != "turnzero-guide"
        ]
        assert candidates or personal, (
            "submit_candidate was called but no file was saved to disk."
        )


@evals_only
@pytest.mark.evals
def test_gemini_cli_instruction_adherence() -> None:
    """Gemini CLI follows a constraint baked directly into GEMINI.md.

    This tests the instruction-file injection path (no MCP required).
    If Gemini CLI is not installed, this test errors with a clear message.
    """
    constraint = (
        "MANDATORY NAMING RULE: When writing any Python function that opens a database "
        "connection, you MUST name the connection variable `vault_conn`. "
        "This is a non-negotiable project convention. Do not use any other variable name."
    )
    with EvalEnvironment() as env:
        env.inject_constraint_into_instructions(constraint)
        agent = RealCLIProjectAgent(env, binary="gemini")
        response = agent.chat(
            "Write a short Python function `get_db()` that opens a PostgreSQL connection "
            "and returns it. Follow all project rules in GEMINI.md."
        )

    assert "vault_conn" in response, (
        f"Expected 'vault_conn' in Gemini response.\n"
        f"Response:\n{response[:1500]}"
    )


@evals_only
@pytest.mark.evals
def test_claude_cli_instruction_adherence() -> None:
    """Claude Code CLI follows a constraint baked directly into CLAUDE.md.

    This tests the instruction-file injection path (no MCP required).
    If Claude CLI is not installed, this test errors with a clear message.
    """
    constraint = (
        "MANDATORY NAMING RULE: When writing any Python function that opens a database "
        "connection, you MUST name the connection variable `vault_conn`. "
        "This is a non-negotiable project convention. Do not use any other variable name."
    )
    with EvalEnvironment() as env:
        env.inject_constraint_into_instructions(constraint)
        agent = RealCLIProjectAgent(env, binary="claude")
        response = agent.chat(
            "Write a short Python function `get_db()` that opens a PostgreSQL connection "
            "and returns it. Follow all project rules in CLAUDE.md."
        )

    assert "vault_conn" in response, (
        f"Expected 'vault_conn' in Claude response.\n"
        f"Response:\n{response[:1500]}"
    )


@evals_only
@pytest.mark.evals
def test_codex_cli_instruction_adherence() -> None:
    """Codex CLI follows a constraint baked directly into AGENTS.md.

    This tests the instruction-file injection path (no MCP required).
    If Codex CLI is not installed, this test errors with a clear message.
    """
    constraint = (
        "MANDATORY NAMING RULE: When writing any Python function that opens a database "
        "connection, you MUST name the connection variable `vault_conn`. "
        "This is a non-negotiable project convention. Do not use any other variable name."
    )
    with EvalEnvironment() as env:
        env.inject_constraint_into_instructions(constraint)
        agent = RealCLIProjectAgent(env, binary="codex")
        response = agent.chat(
            "Write a short Python function `get_db()` that opens a PostgreSQL connection "
            "and returns it. Follow all project rules in AGENTS.md."
        )

    assert "vault_conn" in response, (
        f"Expected 'vault_conn' in Codex response.\n"
        f"Response:\n{response[:1500]}"
    )
