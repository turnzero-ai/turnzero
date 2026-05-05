"""Agentic evaluation harness for TurnZero.

Three agent types:
  SimulatedAgent      – Pure Python tool chain, no LLM. For deterministic unit tests.
  OllamaAgent         – Local Ollama model with live TurnZero tool loop.
  RealCLIProjectAgent – Spawns gemini/claude/codex in an isolated project workspace.

Usage:
  # Unit tests (always run — no LLM required):
  pytest tests/evals/

  # Full agentic benchmarks (requires Ollama and/or real CLIs):
  TURNZERO_RUN_EVALS=1 pytest tests/evals/ -m evals -s
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
from collections.abc import Generator
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Protocol

import httpx
import yaml

OLLAMA_URL = os.environ.get("OLLAMA_HOST", "http://localhost:11434")
OLLAMA_DEFAULT_MODEL = os.environ.get("TURNZERO_EVAL_MODEL", "qwen2.5-coder:7b")


class Agent(Protocol):
    def chat(self, prompt: str) -> str: ...


# ---------------------------------------------------------------------------
# Isolated environment
# ---------------------------------------------------------------------------


class EvalEnvironment:
    """Isolated temp environment for agentic evaluations.

    Copies real bundled blocks into a temp dir, sets TURNZERO_DATA_DIR and
    TURNZERO_TEST_EMBEDDINGS=1 (hash-based embeddings — fast, no Ollama needed
    for index builds in unit tests).
    """

    def __init__(self, workspace_name: str = "test_workspace") -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        self.root = Path(self.temp_dir.name)
        self.data_dir = self.root / "turnzero_data"
        self.project_dir = self.root / workspace_name

        self.data_dir.mkdir(parents=True)
        self.project_dir.mkdir(parents=True)

        self.blocks_dir = self.data_dir / "blocks"
        for tier in ["personal", "local", "community", "candidates"]:
            (self.blocks_dir / tier).mkdir(parents=True)

        self._copy_bundled_blocks()
        self._write_agent_instructions()

        self.env = {
            **os.environ,
            "TURNZERO_DATA_DIR": str(self.data_dir),
            # Hash-based embeddings: fast, deterministic, no Ollama needed for index builds.
            # Retrieval uses lexical similarity in test mode (retrieval.py:_test_similarity).
            "TURNZERO_TEST_EMBEDDINGS": "1",
            # Suppress telemetry in all eval runs — prevents eval UUIDs from polluting
            # PostHog cohorts and inflating real-user counts.
            "TURNZERO_TELEMETRY": "0",
            "PYTHONPATH": str(Path(os.getcwd())),
        }

    def _copy_bundled_blocks(self) -> None:
        import shutil

        repo_root = Path(os.getcwd())

        community_src = repo_root / "data" / "blocks" / "community"
        if community_src.exists():
            shutil.copytree(
                community_src, self.blocks_dir / "community", dirs_exist_ok=True
            )

        personal_src = (
            repo_root / "data" / "templates" / "personal" / "turnzero-guide.yaml"
        )
        if personal_src.exists():
            shutil.copy2(
                personal_src,
                self.blocks_dir / "personal" / "turnzero-guide.yaml",
            )

    def _write_agent_instructions(self) -> None:
        text = (
            "## TurnZero — Expert Prior Injection\n"
            "TurnZero MCP is installed. Follow these rules:\n"
            "1. ALWAYS call list_suggested_blocks before responding to any non-trivial message.\n"
            "2. Use inject_block to retrieve the full text of each relevant prior.\n"
            "3. Call submit_candidate when the user says 'remember this' or corrects you.\n"
        )
        for fname in ["GEMINI.md", "CLAUDE.md", "AGENTS.md"]:
            (self.project_dir / fname).write_text(text)
        rule_dir = self.project_dir / ".cursor" / "rules"
        rule_dir.mkdir(parents=True)
        (rule_dir / "turnzero.mdc").write_text(text)

    def build_index(self) -> None:
        """Build embedding index via CLI using this environment's data dir.

        Works without Ollama because TURNZERO_TEST_EMBEDDINGS=1 is set in self.env,
        making embed() fall back to deterministic hash-based vectors.
        """
        stdout, stderr, rc = self.run_cli(["index", "build"])
        if rc != 0:
            raise RuntimeError(f"index build failed (exit {rc}):\n{stderr}")

    def add_block(
        self,
        slug: str,
        tier: str,
        constraints: list[str],
        domain: str = "eval",
        intent: str = "build",
        tags: list[str] | None = None,
    ) -> None:
        """Write a block YAML and rebuild the index to include it."""
        block_path = self.blocks_dir / tier / f"{slug}.yaml"
        block_path.write_text(
            yaml.dump(
                {
                    "slug": slug,
                    "version": "1.0.0",
                    "domain": domain,
                    "intent": intent,
                    "tier": tier,
                    "constraints": constraints,
                    "anti_patterns": [],
                    "rationale": "Agentic eval test block.",
                    "confidence": 1.0,
                    "context_weight": sum(len(c.split()) * 4 for c in constraints),
                    "last_verified": "2026-05-02",
                    "verification_level": "curated",
                    "tags": tags or [],
                    "provides": [],
                    "conflicts_with": [],
                    "conflicts_with_tags": [],
                    "requires": [],
                }
            )
        )
        self.build_index()

    def inject_constraint_into_instructions(self, constraint: str) -> None:
        """Bake a constraint directly into project instruction files.

        Lets RealCLIProjectAgent tests verify rule-following without MCP.
        """
        rule_section = f"\n\n## MANDATORY Project Rule\n{constraint}\n"
        for fname in ["GEMINI.md", "CLAUDE.md", "AGENTS.md"]:
            f = self.project_dir / fname
            f.write_text((f.read_text() if f.exists() else "") + rule_section)

    def run_cli(self, args: list[str]) -> tuple[str, str, int]:
        """Run turnzero CLI. Returns (stdout, stderr, returncode)."""
        res = subprocess.run(
            [sys.executable, "-m", "turnzero"] + args,
            env=self.env,
            capture_output=True,
            text=True,
            check=False,
        )
        return res.stdout, res.stderr, res.returncode

    def cleanup(self) -> None:
        self.temp_dir.cleanup()

    def __enter__(self) -> EvalEnvironment:
        return self

    def __exit__(self, *_: object) -> None:
        self.cleanup()


# ---------------------------------------------------------------------------
# DirectBridge: call TurnZero Python API with env isolation
# ---------------------------------------------------------------------------


@contextmanager
def _patched_env(**kwargs: str) -> Generator[None, None, None]:
    """Temporarily override os.environ keys for the duration of the block."""
    old = {k: os.environ.get(k) for k in kwargs}
    os.environ.update(kwargs)
    try:
        yield
    finally:
        for k, v in old.items():
            if v is None:
                os.environ.pop(k, None)
            else:
                os.environ[k] = v


class DirectBridge:
    """Call TurnZero Python functions directly, isolated to an EvalEnvironment.

    Patches TURNZERO_DATA_DIR (and TEST_EMBEDDINGS) on every call so the
    functions operate on the eval's temp data dir instead of ~/.turnzero.
    Clears the module-level index cache before each retrieval call to prevent
    stale results from a previous test's data dir.
    """

    def __init__(self, env: EvalEnvironment) -> None:
        self._override = {
            "TURNZERO_DATA_DIR": str(env.data_dir),
            "TURNZERO_TEST_EMBEDDINGS": env.env.get("TURNZERO_TEST_EMBEDDINGS", "1"),
        }

    def list_suggested_blocks(self, prompt: str) -> list[dict[str, Any]]:
        from turnzero.mcp_server import _INDEX_CACHE, _list_suggested_blocks

        with _patched_env(**self._override):
            _INDEX_CACHE.clear()
            return _list_suggested_blocks(prompt)

    def inject_block(self, block_id: str) -> str:
        from turnzero.mcp_server import _inject_block

        with _patched_env(**self._override):
            return _inject_block(block_id)

    def submit_candidate_raw(
        self,
        block_id: str,
        content: str,
        tier: str = "candidates",
    ) -> Path:
        """Write YAML content to candidates/ or blocks/<tier>/. Returns the path."""
        with _patched_env(**self._override):
            from turnzero.config import get_data_dir

            dest_dir = (
                get_data_dir() / "candidates"
                if tier == "candidates"
                else get_data_dir() / "blocks" / tier
            )
            dest_dir.mkdir(parents=True, exist_ok=True)
            path = dest_dir / f"{block_id}.yaml"
            path.write_text(content)
            return path


# ---------------------------------------------------------------------------
# SimulatedAgent: deterministic tool-chain walker (no LLM)
# ---------------------------------------------------------------------------


class SimulatedAgent:
    """Execute the TurnZero MCP tool chain mechanically without an LLM.

    Calls list_suggested_blocks → inject_block for every suggestion.
    Used to verify tool wiring and injection content in deterministic unit tests.
    Exposes tool_calls and injected_blocks for assertion.
    """

    def __init__(self, bridge: DirectBridge) -> None:
        self.bridge = bridge
        self.tool_calls: list[str] = []
        self.injected_blocks: list[str] = []
        self.injected_text: str = ""

    def chat(self, prompt: str) -> str:
        self.tool_calls = []
        self.injected_blocks = []

        self.tool_calls.append("list_suggested_blocks")
        suggestions = self.bridge.list_suggested_blocks(prompt)

        parts: list[str] = []
        for s in suggestions:
            block_id = s["block_id"]
            if block_id == "personal-priors-limit-warning":
                continue
            self.tool_calls.append(f"inject_block:{block_id}")
            self.injected_blocks.append(block_id)
            try:
                text = self.bridge.inject_block(block_id)
                parts.append(text)
            except ValueError:
                pass

        self.injected_text = "\n\n---\n\n".join(parts)
        return self.injected_text


# ---------------------------------------------------------------------------
# OllamaAgent: real local model with TurnZero tool loop
# ---------------------------------------------------------------------------


class OllamaAgent:
    """AI agent using a local Ollama model with the TurnZero tool loop.

    Uses DirectBridge for tool execution — no CLI subprocess or regex parsing.
    Exposes tool_calls_made for assertion in eval tests.

    Requires Ollama running at OLLAMA_HOST (default: http://localhost:11434).
    Set TURNZERO_EVAL_MODEL to override the model (default: qwen2.5-coder:7b).
    """

    def __init__(
        self,
        env: EvalEnvironment,
        model: str = OLLAMA_DEFAULT_MODEL,
    ) -> None:
        self._env = env
        self.bridge = DirectBridge(env)
        self.model = model
        self.messages: list[dict[str, Any]] = []
        self.tool_calls_made: list[str] = []

    def chat(self, prompt: str) -> str:
        self.messages = [{"role": "user", "content": prompt}]
        self.tool_calls_made = []

        system_prompt = (self._env.project_dir / "GEMINI.md").read_text()

        for _ in range(10):
            payload = {
                "model": self.model,
                "messages": [{"role": "system", "content": system_prompt}]
                + self.messages,
                "stream": False,
                "tools": self._tool_schemas(),
            }
            resp = httpx.post(
                f"{OLLAMA_URL}/api/chat", json=payload, timeout=120.0
            ).json()
            message = resp.get("message", {})
            self.messages.append(message)

            if not message.get("tool_calls"):
                return str(message.get("content", ""))

            for tool_call in message["tool_calls"]:
                name = tool_call["function"]["name"]
                raw_args = tool_call["function"]["arguments"]
                args: dict[str, Any] = (
                    json.loads(raw_args) if isinstance(raw_args, str) else raw_args
                )
                self.tool_calls_made.append(name)
                result = self._dispatch(name, args)
                self.messages.append({"role": "tool", "content": result})

        return "Max tool-call turns reached"

    def _tool_schemas(self) -> list[dict[str, Any]]:
        return [
            {
                "type": "function",
                "function": {
                    "name": "list_suggested_blocks",
                    "description": "Get Expert Priors relevant to the current task.",
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "prompt": {
                                "type": "string",
                                "description": "The user's request or task description.",
                            }
                        },
                        "required": ["prompt"],
                    },
                },
            },
            {
                "type": "function",
                "function": {
                    "name": "inject_block",
                    "description": "Retrieve the full constraint text of an Expert Prior.",
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "block_id": {
                                "type": "string",
                                "description": "The block_id returned by list_suggested_blocks.",
                            }
                        },
                        "required": ["block_id"],
                    },
                },
            },
            {
                "type": "function",
                "function": {
                    "name": "submit_candidate",
                    "description": "Save a new rule or correction to remember for future sessions.",
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "block_id": {
                                "type": "string",
                                "description": "Short descriptive slug for the rule.",
                            },
                            "constraints": {
                                "type": "array",
                                "items": {"type": "string"},
                                "description": "The rules to remember, one per string.",
                            },
                            "is_personal": {
                                "type": "boolean",
                                "description": "True if this is a personal preference, False for general rule.",
                            },
                        },
                        "required": ["block_id", "constraints"],
                    },
                },
            },
        ]

    def _dispatch(self, name: str, args: dict[str, Any]) -> str:
        if name == "list_suggested_blocks":
            results = self.bridge.list_suggested_blocks(args.get("prompt", ""))
            return json.dumps(results)

        if name == "inject_block":
            block_id = args.get("block_id", "")
            try:
                return self.bridge.inject_block(block_id)
            except ValueError as e:
                return f"Error: {e}"

        if name == "submit_candidate":
            block_id = args.get("block_id", "new-prior")
            constraints = args.get("constraints", [])
            is_personal = bool(args.get("is_personal", False))
            tier = "personal" if is_personal else "candidates"
            content = yaml.dump(
                {
                    "slug": block_id,
                    "constraints": constraints,
                    "is_personal": is_personal,
                }
            )
            self.bridge.submit_candidate_raw(block_id, content, tier)
            return f"✓ Saved '{block_id}' to {tier}."

        return f"Unknown tool: {name}"


# ---------------------------------------------------------------------------
# RealCLIProjectAgent: spawns an actual AI CLI (gemini/claude/codex)
# ---------------------------------------------------------------------------


class RealCLIProjectAgent:
    """Spawn a real AI CLI in an isolated project workspace.

    The workspace contains TurnZero instruction files. Use
    env.inject_constraint_into_instructions() to bake a constraint directly
    into CLAUDE.md / GEMINI.md / AGENTS.md — this tests instruction following
    without requiring MCP to be configured in the CLI's settings.
    """

    def __init__(self, env: EvalEnvironment, binary: str = "gemini") -> None:
        self._env = env
        self.binary = binary

    def chat(self, prompt: str) -> str:
        if self.binary == "gemini":
            cmd = ["gemini", "-p", prompt, "--yolo"]
        elif self.binary == "claude":
            cmd = ["claude", "--print", "-p", prompt]
        elif self.binary == "codex":
            cmd = [
                "codex",
                "exec",
                "-p",
                prompt,
                "--dangerously-bypass-approvals-and-sandbox",
            ]
        else:
            cmd = [self.binary, "-p", prompt]

        res = subprocess.run(
            cmd,
            env=self._env.env,
            cwd=self._env.project_dir,
            capture_output=True,
            text=True,
            check=False,
        )
        if res.returncode != 0 and not res.stdout.strip():
            raise RuntimeError(
                f"{self.binary} exited {res.returncode}:\n{res.stderr[:500]}"
            )
        return res.stdout
