"""Security validators for TurnZero identifiers and paths."""

from __future__ import annotations

import re
from pathlib import Path


def validate_slug(slug: str) -> None:
    """Strict validation for block IDs / slugs.
    
    Allowlist: a-z, 0-9, underscore, hyphen, dot.
    Length: 3-128 chars.
    No path traversal characters.
    """
    if not slug:
        raise ValueError("Slug cannot be empty.")
    
    # Regex allowlist
    if not re.fullmatch(r"[a-z0-9_\-\.]{3,128}", slug):
        raise ValueError(
            f"Invalid slug: '{slug}'. Must be 3-128 chars (a-z, 0-9, _, -, .)."
        )
    
    # Redundant but safe: explicit check for traversal patterns
    if ".." in slug or "/" in slug or "\\" in slug:
        raise ValueError(f"Security violation: path traversal detected in slug '{slug}'.")


def validate_domain(domain: str) -> None:
    """Strict validation for domain names.
    
    Allowlist: a-z, 0-9, underscore, hyphen.
    Length: 1-64 chars.
    """
    if not domain:
        raise ValueError("Domain cannot be empty.")
        
    if not re.fullmatch(r"[a-z0-9_\-]{1,64}", domain):
        raise ValueError(
            f"Invalid domain: '{domain}'. Must be 1-64 chars (a-z, 0-9, _, -)."
        )


def validate_session_name(name: str) -> None:
    """Strict validation for session names.
    
    Allowlist: a-z, 0-9, underscore, hyphen.
    Length: 1-64 chars.
    """
    if not name:
        raise ValueError("Session name cannot be empty.")
        
    if not re.fullmatch(r"[a-z0-9_\-]{1,64}", name):
        raise ValueError(
            f"Invalid session name: '{name}'. Must be 1-64 chars (a-z, 0-9, _, -)."
        )


def safe_path(base_dir: Path, *parts: str) -> Path:
    """Construct a path and verify it remains within base_dir."""
    try:
        # Construct and resolve absolute path
        target = (base_dir / Path(*parts)).resolve()
        base = base_dir.resolve()
        
        # Verify containment
        if not str(target).startswith(str(base)):
            raise ValueError(f"Security violation: path '{target}' escapes base directory '{base}'.")
            
        return target
    except (OSError, RuntimeError) as e:
        raise ValueError(f"Invalid path construction: {e}")
