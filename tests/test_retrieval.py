"""Tests for intent classification, domain detection, impl gate, and cosine similarity."""

import numpy as np
import pytest

from turnzero.embed import cosine_similarity
from turnzero.retrieval import classify_intent, detect_domain, is_implementation_prompt

# ---------------------------------------------------------------------------
# Intent classifier
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("prompt,expected", [
    # build
    ("help me build a Next.js app with Supabase auth", "build"),
    ("create a new FastAPI endpoint for user registration", "build"),
    ("scaffold a React Native app with Expo", "build"),
    ("set up Docker Compose for my app", "build"),
    ("add authentication to my project", "build"),
    # debug
    ("why is my component not rendering", "debug"),
    ("fix this TypeScript error: cannot find module", "debug"),
    ("my FastAPI endpoint is failing with 422", "debug"),
    ("getting an exception in my async function", "debug"),
    ("this is broken and I don't know why", "debug"),
    # migrate
    ("migrate from Pages Router to App Router", "migrate"),
    ("upgrade my project from Next.js 13 to 15", "migrate"),
    ("convert this class component to a function component", "migrate"),
    ("replace auth-helpers with the new SSR package", "migrate"),
    # review
    ("review this SQL query for performance issues", "review"),
    ("is this the best practice for handling auth in Next.js?", "review"),
    ("check if my Docker Compose setup is production ready", "review"),
    ("should I use interface or type here", "review"),
    # security domain — all four intents
    ("set up secrets management for my web app", "build"),
    ("harden my API against OWASP Top 10 vulnerabilities", "build"),
    ("audit my npm dependencies for CVEs and supply chain risks", "review"),
    ("my AWS access key was leaked in a git commit, how do I rotate it", "debug"),
    ("scan my Docker images for security vulnerabilities before deploying", "build"),
])
def test_classify_intent(prompt: str, expected: str) -> None:
    assert classify_intent(prompt) == expected, (
        f"Expected '{expected}' for prompt: '{prompt}'"
    )


def test_classify_intent_defaults_to_build_on_no_signal() -> None:
    assert classify_intent("xyzzy florp bleep") == "build"


def test_classify_intent_case_insensitive() -> None:
    assert classify_intent("BUILD A NEXT.JS APP") == "build"
    assert classify_intent("FIX THIS ERROR") == "debug"


# ---------------------------------------------------------------------------
# Cosine similarity
# ---------------------------------------------------------------------------

def test_cosine_similarity_identical_vectors() -> None:
    v = np.array([1.0, 2.0, 3.0], dtype=np.float32)
    assert cosine_similarity(v, v) == pytest.approx(1.0, abs=1e-6)


def test_cosine_similarity_orthogonal_vectors() -> None:
    a = np.array([1.0, 0.0], dtype=np.float32)
    b = np.array([0.0, 1.0], dtype=np.float32)
    assert cosine_similarity(a, b) == pytest.approx(0.0, abs=1e-6)


def test_cosine_similarity_opposite_vectors() -> None:
    v = np.array([1.0, 2.0, 3.0], dtype=np.float32)
    assert cosine_similarity(v, -v) == pytest.approx(-1.0, abs=1e-6)


def test_cosine_similarity_zero_vector_returns_zero() -> None:
    v = np.array([1.0, 2.0, 3.0], dtype=np.float32)
    z = np.zeros(3, dtype=np.float32)
    assert cosine_similarity(v, z) == 0.0
    assert cosine_similarity(z, z) == 0.0


# ---------------------------------------------------------------------------
# Domain detection — security
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("prompt", [
    "harden my web app against OWASP Top 10 vulnerabilities",
    "I need to set up secrets management for my application",
    "running a pentest on my API — what should I check?",
    "help me implement IAM least-privilege for my AWS setup",
    "audit my dependencies for CVEs and supply chain risks",
    "rotate my leaked API keys after a security incident",
    "threat model my authentication flow",
    "implement zero trust network access for my microservices",
])
def test_detect_domain_security(prompt: str) -> None:
    assert detect_domain(prompt) == "security", (
        f"Expected domain 'security' for: {prompt!r}"
    )


@pytest.mark.parametrize("prompt", [
    "build a Next.js app",
    "fix my FastAPI endpoint",
    "set up Docker Compose for production",
    "migrate from Pages Router to App Router",
])
def test_detect_domain_not_security(prompt: str) -> None:
    assert detect_domain(prompt) != "security", (
        f"Expected non-security domain for: {prompt!r}"
    )


# ---------------------------------------------------------------------------
# Impl gate — security prompts should pass
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("prompt", [
    "harden my web app against OWASP Top 10 vulnerabilities before launch",
    "I need to rotate my leaked AWS access key after a git commit exposure",
    "audit my npm dependencies for known CVEs and supply chain issues",
    "scan my Docker images for vulnerabilities before deploying to production",
    "set up secrets management using Vault for my microservices project",
    "my API key was leaked in a GitHub commit, how do I rotate it now",
    "accidentally committed AWS secret to public repo, need to remediate",
])
def test_impl_gate_passes_security_prompts(prompt: str) -> None:
    assert is_implementation_prompt(prompt), (
        f"Expected impl gate to PASS for security prompt: {prompt!r}"
    )


@pytest.mark.parametrize("prompt", [
    "what is OWASP",
    "tell me about zero trust",
    "security is important for web apps",
    "I like reading about CVEs",
])
def test_impl_gate_blocks_vague_security_prompts(prompt: str) -> None:
    assert not is_implementation_prompt(prompt), (
        f"Expected impl gate to BLOCK vague prompt: {prompt!r}"
    )


# ---------------------------------------------------------------------------
# Impl gate — domain-agnostic triggering across professions
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("prompt", [
    # Security / IT (Dino's domain)
    "what's the recommended approach for secrets rotation after a credential leak?",
    "help me find SQL injection vulnerabilities in this codebase",
    "we got a CVE on our JWT library, what do we need to patch?",
    "what secrets management approach should we use for our microservices?",
    "how do I set up zero-trust network policies for our infrastructure?",
    "should I use RBAC or ABAC for our IAM model?",
    "what are the OWASP Top 10 risks I need to address before launch?",
    # Medicine
    "what is the recommended dosage of metformin for a CKD stage 3 patient?",
    "how should I adjust warfarin dosing when adding fluconazole?",
    "what are the contraindications for beta-blockers in heart failure?",
    "should I order a CT or MRI for suspected pulmonary embolism?",
    "help me interpret these troponin levels in the context of NSTEMI",
    # Law
    "what are the enforceability requirements for non-compete clauses in California?",
    "how should I structure a limitation of liability clause in a SaaS contract?",
    "what's the difference between indemnification and hold harmless clauses?",
    "should I include a mandatory arbitration clause in our terms of service?",
    "advice on GDPR data processing agreements for a US company with EU customers",
    # Finance
    "what's the best approach for hedging currency exposure with forward contracts?",
    "how should I account for unrealised gains under IFRS 9?",
    "can I use a 1031 exchange for this commercial real estate transaction?",
    "what are the disclosure requirements for material non-public information?",
    "recommendation for structuring a convertible note with a valuation cap",
    # Generic professional questions
    "best way to approach a performance review conversation with an underperformer",
    "what's the difference between gross margin and contribution margin?",
    "i need to prepare for a difficult negotiation with a vendor",
    "help me understand the pros and cons of microservices vs monolith",
])
def test_impl_gate_passes_cross_domain_professional_prompts(prompt: str) -> None:
    assert is_implementation_prompt(prompt), (
        f"Expected impl gate to PASS for professional prompt: {prompt!r}"
    )


@pytest.mark.parametrize("prompt", [
    # Pure social / chitchat
    "how are you",
    "good morning",
    "thanks",
    "thank you so much",
    "sounds good",
    "got it",
    "ok",
    "sure",
    "great",
    "nice",
    # Too vague — no substance, no question, no domain
    "tell me about security",
    "what is machine learning",
    "interesting",
    "I like coding",
    "yes",
    "no",
])
def test_impl_gate_blocks_chitchat_and_vague_prompts(prompt: str) -> None:
    assert not is_implementation_prompt(prompt), (
        f"Expected impl gate to BLOCK chitchat/vague prompt: {prompt!r}"
    )
