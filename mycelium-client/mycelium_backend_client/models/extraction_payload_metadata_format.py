from enum import Enum


class ExtractionPayloadMetadataFormat(str, Enum):
    OBSERVE_SDK_OTEL = "observe-sdk-otel"
    OPENCLAW = "openclaw"

    def __str__(self) -> str:
        return str(self.value)
