import enum
from datetime import datetime

import discord

__all__ = (
    "ChangeType",
    "MessageState",
)


class ChangeType(enum.Enum):
    EDIT = enum.auto()
    DELETE = enum.auto()


class MessageState:
    def __init__(
        self,
        *,
        message: discord.Message,
        changed_through: ChangeType | None,
        changed_at: datetime
    ):
        self.message = message
        self.changed_through = changed_through
        self.changed_at = changed_at
