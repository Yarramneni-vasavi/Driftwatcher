"""Auth sessions: sliding expiry demo."""

session_expiry = "sliding"


def create_session(user_id: str) -> str:
    return f"session:{user_id}:{session_expiry}"
