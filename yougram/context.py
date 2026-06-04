from .models import Dialog

# How many recent turns to keep per user. A "turn" is one user question plus
# the assistant's answer (collapsed to a user→assistant message pair before it
# is stored, so no tool-result dumps are kept). All kept turns are replayed as
# message_history on every request, so this trades follow-up memory for tokens.
HISTORY_TURNS = 10


class ConversationContext:
    """In-memory per-user memory: a 'current chat' and a short message history.

    Set the current chat when the user forwards a message or a read tool resolves
    exactly one chat; read it to scope follow-up questions. History is the last
    `HISTORY_TURNS` turns, passed to the model as `message_history`.
    Not persisted — resets when the process restarts (by design).
    """

    def __init__(self) -> None:
        self._chats: dict[int, Dialog] = {}
        self._history: dict[int, list[list]] = {}

    def set_chat(self, user_id: int, chat: Dialog) -> None:
        self._chats[user_id] = chat

    def get_chat(self, user_id: int) -> Dialog | None:
        return self._chats.get(user_id)

    def append_turn(self, user_id: int, messages: list) -> None:
        """Store one turn's (already trimmed) messages, keeping the last N turns."""
        if not messages:
            return  # nothing survived trimming — don't store an empty turn
        turns = self._history.setdefault(user_id, [])
        turns.append(messages)
        del turns[:-HISTORY_TURNS]  # keep only the last HISTORY_TURNS turns

    def get_history(self, user_id: int) -> list:
        """Flatten the stored turns into one message list for `message_history`."""
        return [msg for turn in self._history.get(user_id, []) for msg in turn]

    def turn_count(self, user_id: int) -> int:
        """How many turns are currently kept for this user (0..HISTORY_TURNS)."""
        return len(self._history.get(user_id, []))

    def clear(self, user_id: int) -> None:
        self._chats.pop(user_id, None)
        self._history.pop(user_id, None)
