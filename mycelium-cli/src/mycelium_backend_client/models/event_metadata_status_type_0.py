from enum import Enum


class EventMetadataStatusType0(str, Enum):
    IN_PROGRESS = "in_progress"
    OPEN = "open"
    RESOLVED = "resolved"

    def __str__(self) -> str:
        return str(self.value)
