from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import Any, Protocol

import httpx
import yaml

OLLAMA_URL = os.environ.get("OLLAMA_HOST", "http://localhost:11434")


class Agent(Protocol):
    def chat(self, prompt: str) -> str: ...


class EvalEnvironment:
    """Isolated environment for agentic evaluations."""

    def __init__(self, workspace_name: str = "test_workspace") -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        self.root = Path(self.temp_dir.name)
        self.data_dir = self.root / "turnzero_data"
        self.project_dir = self.root / workspace_name

        self.data_dir.mkdir(parents=True)
        self.project_dir.mkdir(parents=True)

        # Initialize TurnZero structure mirroring 'turnzero setup'
        self.blocks_dir = self.data_dir / "blocks"
        self.blocks_dir.mkdir(parents=True)
        for tier in ["personal", "local", "community", "candidates"]:
            (self.blocks_dir / tier).mkdir(parents=True)

        # 1. Copy real bundled blocks from the repo
        repo_root = Path(os.getcwd())
        community_src = repo_root / "data" / "blocks" / "community"
        if community_src.exists():
            import shutil

            shutil.copytree(
                community_src, self.blocks_dir / "community", dirs_exist_ok=True
            )

        # 2. Copy the personal template prior
        personal_src = (
            repo_root / "data" / "templates" / "personal" / "turnzero-guide.yaml"
        )
        if personal_src.exists():
            import shutil

            shutil.copy2(
                personal_src, self.blocks_dir / "personal" / "turnzero-guide.yaml"
            )

        # 3. Reproduce the 'global memory' / setup instructions
        self._setup_global_instructions()

        self.env = {
            **os.environ,
            "TURNZERO_DATA_DIR": str(self.data_dir),
            "PYTHONPATH": os.getcwd(),
        }

        # 4. Initial index build
        subprocess.run(
            [sys.executable, "-m", "turnzero", "index", "build"],
            env=self.env,
            check=True,
            capture_output=True,
        )

    def _setup_global_instructions(self) -> None:
        """Mirror what `turnzero setup` does to agent global memory."""
        # In a real setup, this is ~/.gemini/GEMINI.md, etc.
        # Here we put it in the project root so agents pick it up as project-level rules.
        instruction_text = """
## TurnZero — Expert & Personal Prior Injection
TurnZero MCP is installed. Follow these rules to establish a consistent Portable AI Identity:
1. ALWAYS call list_suggested_blocks before responding to ANY non-trivial user message.
2. Use inject_block to retrieve the full text of relevant priors before answering.
3. Call submit_candidate when the user corrects you or says 'remember this'.
"""
        (self.project_dir / "GEMINI.md").write_text(instruction_text)
        (self.project_dir / "CLAUDE.md").write_text(instruction_text)
        (self.project_dir / "AGENTS.md").write_text(instruction_text)

        rule_dir = self.project_dir / ".cursor" / "rules"
        rule_dir.mkdir(parents=True)
        (rule_dir / "turnzero.mdc").write_text(instruction_text)

    def add_block(self, slug: str, tier: str, constraints: list[str]) -> None:
        """Add a block and rebuild index."""
        block_path = self.blocks_dir / tier / f"{slug}.yaml"
        content = {
            "slug": slug,
            "version": "1.0.0",
            "domain": "eval",
            "intent": "build",
            "tier": tier,
            "constraints": constraints,
            "anti_patterns": [],
            "rationale": "Evaluation test case",
            "last_verified": "2026-05-02",
        }
        block_path.write_text(yaml.dump(content))
        subprocess.run(
            [sys.executable, "-m", "turnzero", "index", "build"],
            env=self.env,
            check=True,
            capture_output=True,
        )

    def run_cli(self, args: list[str]) -> str:
        res = subprocess.run(
            [sys.executable, "-m", "turnzero"] + args,
            env=self.env,
            capture_output=True,
            text=True,
            check=False,
        )
        return res.stdout

    def cleanup(self) -> None:
        self.temp_dir.cleanup()


class OllamaAgent:
    """Simulation of an AI agent using a local model and the TurnZero MCP protocol."""

    def __init__(self, env: EvalEnvironment, model: str = "qwen2.5-coder:7b") -> None:
        self.env = env
        self.model = model
        self.messages: list[dict[str, Any]] = []

    def chat(self, prompt: str) -> str:
        self.messages.append({"role": "user", "content": prompt})

        # The system prompt includes the global instructions reproduced in setup
        global_instructions = (self.env.project_dir / "GEMINI.md").read_text()
        system_prompt = f"You are a helpful assistant.\n\n{global_instructions}"

        for _ in range(5):  # Allow up to 5 tool turns
            payload = {
                "model": self.model,
                "messages": [{"role": "system", "content": system_prompt}]
                + self.messages,
                "stream": False,
                "tools": self._get_tools(),
            }

            resp = httpx.post(
                f"{OLLAMA_URL}/api/chat", json=payload, timeout=60.0
            ).json()
            message = resp.get("message", {})
            self.messages.append(message)

            if not message.get("tool_calls"):
                return str(message.get("content", ""))

            # Handle Tool Calls
            for tool_call in message["tool_calls"]:
                name = tool_call["function"]["name"]
                args = tool_call["function"]["arguments"]
                if isinstance(args, str):
                    args = json.loads(args)

                print(f"DEBUG: Agent called {name} with {args}")
                result = self._execute_tool(name, args)
                self.messages.append({"role": "tool", "content": result})

        return "Max turns reached"

    def _get_tools(self) -> list[dict[str, Any]]:
        return [
            {
                "type": "function",
                "function": {
                    "name": "list_suggested_blocks",
                    "description": "Retrieve suggested Expert and Personal Priors.",
                    "parameters": {
                        "type": "object",
                        "properties": {"prompt": {"type": "string"}},
                        "required": ["prompt"],
                    },
                },
            },
            {
                "type": "function",
                "function": {
                    "name": "inject_block",
                    "description": "Get the full text of an Expert Prior by slug.",
                    "parameters": {
                        "type": "object",
                        "properties": {"block_id": {"type": "string"}},
                        "required": ["block_id"],
                    },
                },
            },
            {
                "type": "function",
                "function": {
                    "name": "submit_candidate",
                    "description": "Save a new prior candidate.",
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "block_id": {"type": "string"},
                            "domain": {"type": "string"},
                            "intent": {"type": "string"},
                            "constraints": {
                                "type": "array",
                                "items": {"type": "string"},
                            },
                            "anti_patterns": {
                                "type": "array",
                                "items": {"type": "string"},
                            },
                            "is_personal": {"type": "boolean"},
                        },
                        "required": [
                            "block_id",
                            "domain",
                            "intent",
                            "constraints",
                            "anti_patterns",
                        ],
                    },
                },
            },
        ]

    def _execute_tool(self, name: str, args: dict[str, Any]) -> str:
        if name == "list_suggested_blocks":
            # Mock the real MCP behavior using CLI query
            res = self.env.run_cli(["query", args["prompt"], "--threshold", "0.1"])
            import re

            slugs = re.findall(r"^\s+\d+\.\s+([a-z0-9-]+)", res, re.MULTILINE)
            # Simulate MCP return format
            return json.dumps([{"block_id": s, "score": 0.9} for s in slugs])

        if name == "inject_block":
            # Mock using CLI preview
            return self.env.run_cli(["preview", args["block_id"], "-t", "0.0"])

        if name == "submit_candidate":
            # Just acknowledge for the test
            return "✓ Candidate saved for review."

        return "Unknown tool"


class RealCLIProjectAgent:
    """Uses a real CLI (gemini/claude/codex) in a controlled project environment."""

    def __init__(self, env: EvalEnvironment, binary_name: str = "gemini") -> None:
        self.env = env
        self.binary = binary_name

    def chat(self, prompt: str) -> str:
        cmd = [self.binary, "-p", prompt]
        if self.binary == "gemini":
            cmd.append("--yolo")
        elif self.binary == "claude":
            cmd.append("--print")
        elif self.binary == "codex":
            cmd = [
                "codex",
                "exec",
                "-p",
                prompt,
                "--dangerously-bypass-approvals-and-sandbox",
            ]

        # Run in the project dir where GEMINI.md/CLAUDE.md exists
        res = subprocess.run(
            cmd,
            env=self.env.env,
            cwd=self.env.project_dir,
            capture_output=True,
            text=True,
            check=False,
        )
        return res.stdout
