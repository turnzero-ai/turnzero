
import os
import json
import subprocess
import tempfile
import httpx
import sys
from pathlib import Path
from typing import Any, Dict, List

OLLAMA_URL = os.environ.get("OLLAMA_HOST", "http://localhost:11434")
DEFAULT_MODEL = "qwen2.5-coder:7b"

class EvalEnvironment:
    def __init__(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.data_dir = Path(self.temp_dir.name)
        self.blocks_dir = self.data_dir / "blocks" / "local"
        self.blocks_dir.mkdir(parents=True)
        self.env = {
            **os.environ,
            "TURNZERO_DATA_DIR": str(self.data_dir),
            "PYTHONPATH": os.getcwd()
        }

    def add_block(self, slug: str, domain: str, constraints: List[str]):
        block_path = self.blocks_dir / f"{slug}.yaml"
        content = {
            "slug": slug,
            "version": "1.0.0",
            "domain": domain,
            "intent": "build",
            "constraints": constraints,
            "anti_patterns": [],
            "rationale": "Testing",
            "last_verified": "2026-05-02"
        }
        import yaml
        block_path.write_text(yaml.dump(content))
        # Build index for this isolated env
        subprocess.run(
            [sys.executable, "-m", "turnzero", "index", "build"],
            env=self.env,
            check=True,
            capture_output=True
        )

    def run_cli(self, args: List[str]) -> str:
        res = subprocess.run(
            [sys.executable, "-m", "turnzero"] + args,
            env=self.env,
            capture_output=True,
            text=True
        )
        return res.stdout

    def cleanup(self):
        self.temp_dir.cleanup()

class SimulatedAgent:
    def __init__(self, env: EvalEnvironment, model: str = DEFAULT_MODEL):
        self.env = env
        self.model = model
        self.messages = []

    def chat(self, prompt: str) -> str:
        self.messages.append({"role": "user", "content": prompt})
        
        system_prompt = (
            "You are a helpful assistant. "
            "Workflow: "
            "1. Call 'turnzero_query' with the user prompt to find relevant rules. "
            "2. Once you have the results, provide the final answer following those rules. "
            "Do not call the tool more than once per user request."
        )
        
        for i in range(3): # Max 3 turns
            payload = {
                "model": self.model,
                "messages": [{"role": "system", "content": system_prompt}] + self.messages,
                "stream": False,
            }
            if i == 0: # Only provide tool in first turn to force answer in second
                payload["tools"] = [
                    {
                        "type": "function",
                        "function": {
                            "name": "turnzero_query",
                            "description": "Get coding priors for a prompt",
                            "parameters": {
                                "type": "object",
                                "properties": {
                                    "query_text": {"type": "string", "description": "The search query"}
                                },
                                "required": ["query_text"]
                            }
                        }
                    }
                ]
            resp = httpx.post(f"{OLLAMA_URL}/api/chat", json=payload, timeout=60.0).json()
            message = resp.get("message", {})
            self.messages.append(message)

            content = message.get("content", "")
            tool_calls = message.get("tool_calls", [])

            # Fallback: Parse content if it looks like tool call JSON
            if not tool_calls and content.strip().startswith("{"):
                try:
                    data = json.loads(content)
                    if "name" in data:
                        tool_calls = [{"function": data}]
                except Exception:
                    pass

            if not tool_calls:
                return content

            # Handle Tool Calls
            for tool_call in tool_calls:
                name = tool_call["function"]["name"]
                if name == "turnzero_query":
                    args = tool_call["function"]["arguments"]
                    if isinstance(args, str):
                        args = json.loads(args)
                    q_text = args.get("query_text") or args.get("prompt") or prompt
                    query_res = self.env.run_cli(["query", q_text, "--threshold", "0.1"])

                    self.messages.append({
                        "role": "tool",
                        "content": f"Suggested Blocks:\n{query_res}"
                    })

        
        return "Error: Max turns reached"
