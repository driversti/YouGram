from .models import Dialog


class ConversationContext:
    """In-memory per-user 'current chat' memory.

    Set when the user forwards a message; read to scope follow-up questions.
    Not persisted — resets when the process restarts (by design).
    """

    def __init__(self) -> None:
        self._chats: dict[int, Dialog] = {}

    def set_chat(self, user_id: int, chat: Dialog) -> None:
        self._chats[user_id] = chat

    def get_chat(self, user_id: int) -> Dialog | None:
        return self._chats.get(user_id)

    def clear(self, user_id: int) -> None:
        self._chats.pop(user_id, None)
