from enum import Enum


class AgentReplyAction(str, Enum):
    ACCEPT = "accept"
    COUNTER_OFFER = "counter_offer"
    REJECT = "reject"

    def __str__(self) -> str:
        return str(self.value)
