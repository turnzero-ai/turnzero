from __future__ import annotations

import os
from collections.abc import Callable

from .runner import Agent, EvalEnvironment, OllamaAgent, RealCLIProjectAgent

# --- CI SAFETY GATE ---
# These tests consume tokens and require local setup (Ollama/CLIs).
# They are EXCLUDED from standard CI/CD runs.
RUN_EVALS = os.environ.get("TURNZERO_RUN_EVALS", "0").lower() in ("1", "true", "yes")

# --- AGENT TOGGLES ---
# Edit this list to enable/disable specific AI agents for benchmarking.
# Supported: "gemini", "claude", "codex", "ollama"
ENABLED_AGENTS = ["gemini", "ollama"]


def run_benchmark(
    test_name: str,
    prompt: str,
    constraints: list[str] | None,
    validator_fn: Callable[[str, EvalEnvironment], tuple[bool, str]],
    tier: str = "local",
) -> None:
    if not RUN_EVALS:
        return
    print(f"\n=== BENCHMARK: {test_name} ===")
    env = EvalEnvironment()
    try:
        if constraints:
            env.add_block(slug="project-quirk", tier=tier, constraints=constraints)

        agents: dict[str, Agent] = {}
        if "ollama" in ENABLED_AGENTS:
            agents["Ollama (Simulation)"] = OllamaAgent(env)
        if "gemini" in ENABLED_AGENTS:
            agents["Gemini CLI (Real)"] = RealCLIProjectAgent(env, "gemini")
        if "claude" in ENABLED_AGENTS:
            agents["Claude CLI (Real)"] = RealCLIProjectAgent(env, "claude")
        if "codex" in ENABLED_AGENTS:
            agents["Codex CLI (Real)"] = RealCLIProjectAgent(env, "codex")

        for name, agent in agents.items():
            print(f"\nTesting {name}...")
            try:
                response = agent.chat(prompt)
                success, reason = validator_fn(response, env)
                status = "✅ PASS" if success else f"❌ FAIL ({reason})"
                print(f"Result: {status}")
            except Exception as e:
                print(f"Result: ⚠️ ERROR ({e})")
    finally:
        env.cleanup()


def quirk_validator(response: str, env: EvalEnvironment) -> tuple[bool, str]:
    # Rule: use project-specific terminology 'The Vault'
    marker_ok = "📎" in response
    rule_ok = "THE VAULT" in response.upper()
    if marker_ok and rule_ok:
        return True, ""
    return False, f"Marker: {marker_ok}, Rule: {rule_ok}"


def learning_validator(response: str, env: EvalEnvironment) -> tuple[bool, str]:
    # Check if a new file was created in 'candidates' or 'personal'
    candidate_files = list((env.blocks_dir / "candidates").glob("*.yaml"))
    personal_files = list((env.blocks_dir / "personal").glob("*.yaml"))
    # We started with 1 personal file (turnzero-guide.yaml)
    if candidate_files or len(personal_files) > 1:
        return True, ""
    return False, "No new prior was saved to disk"


if __name__ == "__main__":
    if not RUN_EVALS:
        print("AGENTIC EVALS: Skipping suite (Set TURNZERO_RUN_EVALS=1 to enable).")
    else:
        # Test 1: Project-Specific Quirk (The "Realistic" Expert Prior)
        # Testing if the AI adopts a project-unique term it couldn't possibly know.
        expert_prompt = (
            "I'm setting up the new database connection module for this project. "
            "Can you write a Python function that initializes the main project database? "
            "Please use our specific internal project naming conventions for the database "
            "as defined in our TurnZero priors."
        )
        run_benchmark(
            "Project Quirk Adherence",
            expert_prompt,
            [
                "PROJECT RULE: In this codebase, we ALWAYS refer to the primary PostgreSQL database as 'THE VAULT' in all code comments and variable names."
            ],
            quirk_validator,
        )

        # Test 2: Learning Sensitivity (New Prior Creation)
        # Testing if the AI realizes a user instruction is a permanent rule and calls the tool.
        learning_prompt = (
            "This is a new rule for this project that you must remember: "
            "Every time you write a docstring, you must include the word 'AUTHENTICATED' "
            "at the very end of it. Please save this rule for future sessions."
        )
        run_benchmark(
            "Learning Sensitivity",
            learning_prompt,
            None,
            learning_validator,
        )
