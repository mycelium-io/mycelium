from enum import Enum


class L9Kind(str, Enum):
    KIND_COMMIT = "commit"
    KIND_CONTINGENCY = "contingency"
    KIND_EXCHANGE = "exchange"
    KIND_INTENT = "intent"
    KIND_KNOWLEDGE = "knowledge"

    def __str__(self) -> str:
        return str(self.value)
