from dataclasses import dataclass


@dataclass
class ForwardSource:
    """Where a forwarded message came from.

    `resolvable` is True when Telegram exposed the origin chat (we have a
    `chat_id` to read). It is False when the origin is hidden by the sender's
    privacy settings — then only `name` may be available.
    """

    resolvable: bool
    chat_id: int | None = None
    name: str | None = None


def extract_forward_source(message) -> ForwardSource | None:
    """Parse Telethon forward metadata; return None if it isn't a forward."""
    fwd = getattr(message, "fwd_from", None)
    if fwd is None:
        return None

    from_id = getattr(fwd, "from_id", None)
    if from_id is None:
        # Origin hidden by privacy; only a display name may be present.
        return ForwardSource(resolvable=False, name=getattr(fwd, "from_name", None))

    chat_id = (
        getattr(from_id, "channel_id", None)
        or getattr(from_id, "user_id", None)
        or getattr(from_id, "chat_id", None)
    )
    return ForwardSource(resolvable=True, chat_id=chat_id)
