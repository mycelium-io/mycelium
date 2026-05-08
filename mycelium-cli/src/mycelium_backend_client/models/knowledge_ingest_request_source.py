from enum import Enum


class KnowledgeIngestRequestSource(str, Enum):
    CHANNEL_MESSAGE = "channel_message"
    LEGACY = "legacy"
    MEMORY_SET = "memory_set"

    def __str__(self) -> str:
        return str(self.value)
