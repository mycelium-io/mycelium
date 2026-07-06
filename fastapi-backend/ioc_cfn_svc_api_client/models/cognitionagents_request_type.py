from enum import Enum


class CognitionagentsRequestType(str, Enum):
    REQ_TYPE_KNOWLEDGE_VECTORS_QUERY = "KNOWLEDGE_VECTORS_QUERY"
    REQ_TYPE_KNOWLEDGE_VECTORS_UPSERT = "KNOWLEDGE_VECTORS_UPSERT"

    def __str__(self) -> str:
        return str(self.value)
