from enum import Enum


class EventProvenanceRefType(str, Enum):
    COMMIT = "commit"
    ISSUE = "issue"
    MESSAGE = "message"
    PAGE = "page"
    PR = "pr"

    def __str__(self) -> str:
        return str(self.value)
