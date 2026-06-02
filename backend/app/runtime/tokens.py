"""Token estimation helpers shared by adapters."""


def estimate_tokens(text: str) -> int:
    """Rough token estimate when the provider omits usage (≈4 chars/token)."""
    if not text:
        return 0
    return max(1, len(text) // 4)
