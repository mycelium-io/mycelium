from enum import Enum


class KnowledgeGraphStoreRequestMemoryTypeType0(str, Enum):
    EPISODIC = "Episodic"
    PROCEDURAL = "Procedural"
    SEMANTIC = "Semantic"

    def __str__(self) -> str:
        return str(self.value)
