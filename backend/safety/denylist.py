"""Destructive-op classifier.

Three levels:
  - safe          : agent may proceed
  - destructive   : requires an approval token minted via the control plane
  - catastrophic  : the orchestrator hard-refuses; no token can authorize it

The classifier is regex-first so we fail closed on known-bad patterns even if
the LLM classifier is flaky. An optional LLM pass using the QA model (Haiku)
only elevates a 'safe' classification; it cannot lower 'catastrophic'.
"""
from __future__ import annotations

import re
from typing import Literal


Severity = Literal["safe", "destructive", "catastrophic"]


# Hardcoded catastrophic — the orchestrator refuses these outright.
_CATASTROPHIC = [
    re.compile(r"rm\s+-rf\s+/(?:\s|$|[^\w])"),            # rm -rf / ...
    re.compile(r"rm\s+-rf\s+\*"),
    re.compile(r"\bshred\b"),
    re.compile(r"\bdd\s+if=/dev/"),
    re.compile(r"\bmkfs\b"),
    re.compile(r"\bDROP\s+TABLE\b", re.IGNORECASE),
    re.compile(r"\bTRUNCATE\s+TABLE\b", re.IGNORECASE),
    re.compile(r"git\s+push\s+.*--force\b"),
    re.compile(r"git\s+push\s+.*-f\b"),
    re.compile(r"git\s+reset\s+--hard\b"),
    re.compile(r"git\s+clean\s+-[a-z]*f"),
    re.compile(r"\bwallet\.dat\b"),                       # Bitcoin wallet
    re.compile(r"\bmacaroon\b", re.IGNORECASE),
    re.compile(r"/chainstate\b"),
    re.compile(r">\s*/etc/"),                             # writes inside /etc
    re.compile(r"\bcurl\b[^|]*\|\s*(sudo\s+)?(sh|bash)"), # curl | sh piping
    re.compile(r"\bchmod\s+-R\s+777\b"),
    re.compile(r"\bchown\s+-R\s+root\b"),
]

# Destructive — allowed with an approval token.
_DESTRUCTIVE = [
    re.compile(r"\bALTER\s+TABLE\b", re.IGNORECASE),
    re.compile(r"\bDROP\s+(COLUMN|INDEX|CONSTRAINT)\b", re.IGNORECASE),
    re.compile(r"\bDELETE\s+FROM\b", re.IGNORECASE),
    re.compile(r"\balembic\s+(downgrade|stamp)\b"),
    re.compile(r"\bterraform\s+destroy\b"),
    re.compile(r"\bterraform\s+apply\b"),
    re.compile(r"\bnpm\s+install\s+"),           # dependency changes
    re.compile(r"\buv\s+add\s+"),
    re.compile(r"\buv\s+remove\s+"),
    re.compile(r"\bpip\s+(install|uninstall)\b"),
    re.compile(r"\bcargo\s+add\b"),
    re.compile(r"\bdocker\s+(rmi|rm)\s+"),
    re.compile(r"\baws\s+s3\s+rm\b"),
    re.compile(r"\brm\s+-rf\b"),                  # any rm -rf (not caught by catastrophic's / match)
]


def classify_command(cmd: str) -> Severity:
    """Classify a shell command or SQL statement by severity."""
    if not cmd or not cmd.strip():
        return "safe"
    for pat in _CATASTROPHIC:
        if pat.search(cmd):
            return "catastrophic"
    for pat in _DESTRUCTIVE:
        if pat.search(cmd):
            return "destructive"
    return "safe"


def requires_approval(cmd: str) -> bool:
    return classify_command(cmd) != "safe"


def is_forbidden(cmd: str) -> bool:
    return classify_command(cmd) == "catastrophic"


def classify_plan_step(description: str, files_touched: list[str]) -> Severity:
    """Best-effort classifier over a TaskStep. Used before the agent runs."""
    text = description or ""
    if any(f.startswith(("/etc/", "/root/", "/.env", "wallet.dat")) for f in files_touched):
        return "catastrophic"
    if any(keyword in text.lower() for keyword in (
        "drop table", "truncate", "force push", "delete all", "wipe",
        "rm -rf", "mkfs", "shred",
    )):
        return classify_command(text) if classify_command(text) != "safe" else "destructive"
    if any(keyword in text.lower() for keyword in (
        "migration", "alter table", "drop column", "dependency bump",
        "upgrade ", "downgrade ", "infra change", "terraform",
    )):
        return "destructive"
    return "safe"
