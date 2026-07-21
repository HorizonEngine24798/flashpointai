"""llama.cpp inference layer."""

from crisis_room.llm.contracts import FakeLLMClient, LLMClient, LLMMessage, LLMRequest
from crisis_room.llm.llama_cpp_client import LlamaCppServerClient
from crisis_room.llm.scripted_client import ScriptedLLMClient
from crisis_room.llm.task_contracts import (
    AdvisorCouncilResponse,
    BackchannelCounterpartResponse,
    BackchannelStateChange,
    EventCandidate,
    EventCreatorResponse,
    FactionDecision,
    FactionTurnResponse,
    InternalDebate,
    InternationalPressure,
    MultiIntentCompilation,
    PerceptionUpdate,
    PublicBrief,
    SignalDistortionResponse,
)

__all__ = [
    "AdvisorCouncilResponse",
    "BackchannelCounterpartResponse",
    "BackchannelStateChange",
    "EventCandidate",
    "EventCreatorResponse",
    "FakeLLMClient",
    "FactionDecision",
    "FactionTurnResponse",
    "InternalDebate",
    "InternationalPressure",
    "LLMClient",
    "LLMMessage",
    "LLMRequest",
    "LlamaCppServerClient",
    "MultiIntentCompilation",
    "PerceptionUpdate",
    "PublicBrief",
    "ScriptedLLMClient",
    "SignalDistortionResponse",
]
