from __future__ import annotations

import os
from collections.abc import Callable

from .runner import Agent, EvalEnvironment, OllamaAgent, RealCLIProjectAgent

# --- CI SAFETY GATE ---
# These tests consume tokens and require local setup (Ollama/CLIs).
# They are EXCLUDED from standard CI/CD runs.
RUN_EVALS = os.environ.get("TURNZERO_RUN_EVALS", "0").lower() in ("1", "true", "yes")


def run_benchmark(
    test_name: str,
    prompt: str,
    constraints: list[str] | None,
    validator_fn: Callable[[str, EvalEnvironment], tuple[bool, str]],
    tier: str = "local",
) -> None:
    if not RUN_EVALS:
        print(f"Skipping benchmark '{test_name}' (set TURNZERO_RUN_EVALS=1 to run)")
        return

    print(f"\n=== BENCHMARK: {test_name} ===")
    print(f"Prompt length: {len(prompt)} characters")
    if constraints:
        print(f"Rule: {constraints[0]}")

    env = EvalEnvironment()
    try:
        if constraints:
            env.add_block(slug="eval-rule", tier=tier, constraints=constraints)

        agents: dict[str, Agent] = {
            "Ollama (Simulation)": OllamaAgent(env),
            "Gemini CLI (Real)": RealCLIProjectAgent(env, "gemini"),
            # "Claude CLI (Real)": RealCLIProjectAgent(env, "claude"), # Tokens
        }

        for name, agent in agents.items():
            print(f"\nTesting {name}...")
            try:
                response = agent.chat(prompt)
                if not response or len(response.strip()) < 5:
                    print("Result: ⚠️ EMPTY RESPONSE")
                    continue

                success, reason = validator_fn(response, env)
                status = "✅ PASS" if success else f"❌ FAIL ({reason})"
                print(f"Result: {status}")
            except Exception as e:
                print(f"Result: ⚠️ ERROR ({e})")

    finally:
        env.cleanup()


def learning_validator(response: str, env: EvalEnvironment) -> tuple[bool, str]:
    # Test if the agent realized it should save a new rule
    # Check if a file was created in 'candidates' dir.
    candidate_files = list((env.blocks_dir / "candidates").glob("*.yaml"))
    if candidate_files:
        return True, ""

    # Check if tool call was in response (for simulation)
    if "submit_candidate" in response.lower() or "✓ Candidate saved" in response:
        return True, ""

    return False, "No candidate prior submitted"


if __name__ == "__main__":
    if not RUN_EVALS:
        print("AGENTIC EVALS: Skipping suite (Set TURNZERO_RUN_EVALS=1 to enable).")
    else:
        # Test 1: Expert Prior Adherence (Library Enforcement)
        # Testing if the agent switches from its 'default' library (requests) to our preferred one (httpx)
        expert_prompt = (
            "I need to write a Python script that fetches JSON data from an external API "
            "endpoint 'https://api.example.com/data'. Can you provide the code for this?"
        )
        run_benchmark(
            "Library Enforcement Adherence",
            expert_prompt,
            [
                "PROJECT RULE: Always use the 'httpx' library for all network requests. Never use 'requests'."
            ],
            lambda r, e: (
                "import httpx" in r and "import requests" not in r,
                "Failed to use httpx or used requests",
            ),
        )

        # Test 2: Naming Convention Adherence
        naming_prompt = (
            "I'm creating a new internal service class that handles user authentication logic. "
            "How should I name this class according to our project's standards?"
        )
        run_benchmark(
            "Naming Convention Adherence",
            naming_prompt,
            [
                "NAMING RULE: All service classes handling logic must use the suffix 'CoreLogic' (e.g. AuthCoreLogic)."
            ],
            lambda r, e: ("AuthCoreLogic" in r, "Did not follow naming convention"),
        )

        # Test 3: Learning Sensitivity (New Prior Creation)

        learning_prompt = (
            "Listen closely, this is very important for our workflow: "
            "From now on, every time we create a new Python test file in this repository, "
            "we MUST name it using the 'check_' prefix instead of 'test_'. "
            "Please remember this instruction for our future coding sessions."
        )
        run_benchmark(
            "Learning Sensitivity",
            learning_prompt,
            None,  # No existing rule
            learning_validator,
        )

        # Test 3: Portable Identity (Personal Prior)
        identity_prompt = (
            "I need to send an urgent email to the technical lead of this project "
            "regarding the latest deployment issues. How should I properly address "
            "them in the greeting of the email according to our project's "
            "established communication identity and TurnZero standards?"
        )
        run_benchmark(
            "Portable Identity Adherence",
            identity_prompt,
            [
                "IDENTITY RULE: Always refer to the tech lead as 'Supreme Commander' in all communications."
            ],
            lambda r, e: (
                "SUPREME COMMANDER" in r.upper(),
                "Did not use identity-specific term",
            ),
            tier="personal",
        )
