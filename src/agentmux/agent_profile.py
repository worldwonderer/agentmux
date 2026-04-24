"""Agent profiles defining REPL interaction patterns for different AI agents."""

import logging
from dataclasses import dataclass


@dataclass(frozen=True)
class AgentProfile:
    """Agent-specific behavior profile for idle detection and session management."""

    name: str
    idle_pattern: str
    ctx_pattern: str | None
    default_repl_cmd: str
    default_startup_delay: float
    has_trust_prompt: bool = False
    has_bypass_warning: bool = False


PROFILES: dict[str, AgentProfile] = {
    "claude": AgentProfile(
        name="claude",
        idle_pattern=r"❯\s*$",
        ctx_pattern=r"ctx:(\d+)%",
        default_repl_cmd="claude",
        default_startup_delay=3.0,
        has_trust_prompt=True,
        has_bypass_warning=True,
    ),
    "codex": AgentProfile(
        name="codex",
        idle_pattern=r"·\s+~\S*\s*$",
        ctx_pattern=None,
        default_repl_cmd="codex --no-alt-screen --full-auto",
        default_startup_delay=5.0,
        has_trust_prompt=True,
    ),
}


def get_profile(name: str) -> AgentProfile:
    """Return the profile for the given agent name, falling back to claude."""
    profile = PROFILES.get(name)
    if profile is None:
        logging.getLogger("bridge").warning(
            "Unknown agent '%s', falling back to 'claude'. Supported: %s",
            name,
            ", ".join(sorted(PROFILES)),
        )
        return PROFILES["claude"]
    return profile
