from datetime import datetime
from typing import Literal

from pydantic import BaseModel

DialogKind = Literal["channel", "group", "user"]


class Message(BaseModel):
    id: int
    date: datetime
    sender: str | None
    text: str


class Dialog(BaseModel):
    id: int
    name: str
    kind: DialogKind
