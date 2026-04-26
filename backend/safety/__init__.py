"""DevForge SafetyGuard — denylist + approval + scope + injection scrub.

The orchestrator uses these modules BEFORE handing work to agents. Agents
themselves have no direct access to mint / approve / bypass anything.
"""
from .denylist import (
    Severity,
    classify_command,
    classify_plan_step,
    is_forbidden,
    requires_approval,
)
from .injection_scrub import scrub
from .approval import list_pending, mint, verify_and_consume
from .scope import EGRESS_ALLOWLIST, ensure_path_in_scope, is_host_allowed
from .secret_redact import redact_secrets, scan_secrets

__all__ = [
    "Severity",
    "classify_command",
    "classify_plan_step",
    "is_forbidden",
    "requires_approval",
    "scrub",
    "mint",
    "verify_and_consume",
    "list_pending",
    "ensure_path_in_scope",
    "is_host_allowed",
    "EGRESS_ALLOWLIST",
    "redact_secrets",
    "scan_secrets",
]
