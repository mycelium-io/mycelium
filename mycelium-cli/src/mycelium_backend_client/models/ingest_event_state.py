from enum import Enum


class IngestEventState(str, Enum):
    DEDUPED = "deduped"
    DISABLED = "disabled"
    ERROR = "error"
    OK = "ok"
    REFUSED = "refused"
    SKIPPED = "skipped"
    TRUNCATED = "truncated"

    def __str__(self) -> str:
        return str(self.value)
