from enum import Enum


class ExtractionPayloadMetadataFormat(str, Enum):
    OBSERVE_SDK_OTEL = "observe-sdk-otel"
    OPENCLAW = "openclaw"
    OTEL_TRACE = "otel-trace"

    def __str__(self) -> str:
        return str(self.value)
