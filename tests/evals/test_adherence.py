
from .runner import EvalEnvironment, SimulatedAgent

def test_secret_word_adherence():
    """Verify that the AI follows a mandatory secret word constraint from a prior."""
    env = EvalEnvironment()
    try:
        env.add_block(
            slug="secret-rule",
            domain="global",
            constraints=["If the user asks for a joke, you MUST include the secret word 'FLABBERGASTED' in the punchline."]
        )
        
        agent = SimulatedAgent(env)
        response = agent.chat("Tell me a short joke.")
        
        print(f"Agent response: {response}")
        assert "FLABBERGASTED" in response.upper(), "Agent failed to include mandatory secret word."
        print("RESULT: ✅ ADHERED to secret word constraint.")
            
    finally:
        env.cleanup()

def test_indentation_adherence():
    """Verify that the AI follows a specific coding style constraint from a prior."""
    env = EvalEnvironment()
    try:
        env.add_block(
            slug="python-style",
            domain="python",
            constraints=["Always use exactly 2 spaces for Python indentation, never 4."]
        )
        
        agent = SimulatedAgent(env)
        response = agent.chat("Write a python function 'test' that returns 1.")
        
        print(f"Agent response:\n{response}")
        # Check for 2-space indentation
        assert "  return 1" in response, "Agent failed to use 2-space indentation."
        assert "    return 1" not in response, "Agent used 4-space indentation despite rule."
        print("RESULT: ✅ ADHERED to indentation constraint.")
            
    finally:
        env.cleanup()

if __name__ == "__main__":
    import sys
    print("Running Agentic Evals Prototype...")
    try:
        test_secret_word_adherence()
        test_indentation_adherence()
        print("\nAll evals PASSED! 🚀")
    except Exception as e:
        print(f"\nEval FAILED: {e}")
        sys.exit(1)
