from enum import Enum


class KnowledgeIngestRequestSource(str, Enum):
    CHANNEL_MESSAGE = "channel_message"
    CONTEXT_FILE = "context_file"
    LEGACY = "legacy"
    MEMORY_SET = "memory_set"

    def __str__(self) -> str:
        return str(self.value)
