from enum import Enum


class MessageCreateMessageType(str, Enum):
    ANNOUNCE = "announce"
    BROADCAST = "broadcast"
    DELEGATE = "delegate"
    DIRECT = "direct"
    EVENT = "event"

    def __str__(self) -> str:
        return str(self.value)
