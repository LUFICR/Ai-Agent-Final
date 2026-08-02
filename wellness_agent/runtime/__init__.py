"""Runtime Foundation (GAP_ANALYSIS.md M6, RFC-002 Ch3/Ch4).

Immutable request-scoped RuntimeContext, the RuntimeEngine contract,
EngineUpdate, EngineMetrics, EngineResult states, and contract adapters
wrapping the existing deterministic engines.
"""

from .adapters import (
    BehaviorAdapter,
    BeliefAdapter,
    EmotionAdapter,
    HypothesisAdapter,
    LearningAdapter,
    MemoryAdapter,
    ProactiveAdapter,
    ReportsAdapter,
    RootCauseAdapter,
    RoutineAdapter,
    SelfEvaluationAdapter,
    WhyAdapter,
)
from .conversation_engine import ConversationEngine, PersistenceEngine
from .conversation_runtime import (
    ConversationRequest,
    ConversationResponse,
    ConversationRuntime,
)
from .diagnostics import DecisionTrace, Diagnostic
from .engine_metrics import EngineMetrics
from .engine_result import EngineResult
from .engine_update import EngineUpdate
from .intent_resolver import (
    INTENT_PRIORITIES,
    Intent,
    IntentGraph,
    IntentRelationship,
    IntentResolverEngine,
    resolve_intents,
)
from .merge_engine import (
    ContextMergeEngine,
    MergeError,
    MergeHistoryEntry,
    MergeResult,
    MergeSummary,
    RuntimeEvent,
)
from .pipeline_executor import (
    PipelineError,
    PipelineExecutor,
    PipelineStage,
    RetryManager,
    StageResult,
    TimeoutManager,
)
from .registry import (
    CircularDependencyError,
    EngineRegistry,
    RegistrationError,
    UnknownEngineError,
)
from .runtime_context import (
    ConversationContext,
    DiagnosticsContext,
    ExecutionContext,
    MemoryContext,
    MetricsContext,
    RequestContext,
    RuntimeContext,
    RuntimeMetadata,
    RuntimeStage,
    RuntimeState,
    StreamingContext,
)
from .runtime_engine import (
    BaseEngine,
    EngineCategory,
    EngineMetadata,
    RetryPolicy,
    RuntimeEngine,
)
from .runtime_orchestrator import (
    EventDispatcher,
    MetricsCollector,
    PersistenceCoordinator,
    RuntimeExecutionError,
    RuntimeOrchestrator,
    RuntimeResult,
    StreamCoordinator,
)

__all__ = [
    "BaseEngine",
    "BehaviorAdapter",
    "BeliefAdapter",
    "CircularDependencyError",
    "ContextMergeEngine",
    "ConversationContext",
    "ConversationEngine",
    "ConversationRequest",
    "ConversationResponse",
    "ConversationRuntime",
    "DecisionTrace",
    "Diagnostic",
    "DiagnosticsContext",
    "EmotionAdapter",
    "EngineCategory",
    "EngineMetadata",
    "EngineMetrics",
    "EngineRegistry",
    "EngineResult",
    "EngineUpdate",
    "EventDispatcher",
    "ExecutionContext",
    "HypothesisAdapter",
    "INTENT_PRIORITIES",
    "Intent",
    "IntentGraph",
    "IntentRelationship",
    "IntentResolverEngine",
    "LearningAdapter",
    "MemoryAdapter",
    "MemoryContext",
    "MergeError",
    "MergeHistoryEntry",
    "MergeResult",
    "MergeSummary",
    "MetricsCollector",
    "MetricsContext",
    "PersistenceCoordinator",
    "PersistenceEngine",
    "PipelineError",
    "PipelineExecutor",
    "PipelineStage",
    "ProactiveAdapter",
    "RegistrationError",
    "ReportsAdapter",
    "RequestContext",
    "RetryManager",
    "RetryPolicy",
    "RootCauseAdapter",
    "RoutineAdapter",
    "RuntimeContext",
    "RuntimeEngine",
    "RuntimeEvent",
    "RuntimeExecutionError",
    "RuntimeMetadata",
    "RuntimeOrchestrator",
    "RuntimeResult",
    "RuntimeStage",
    "RuntimeState",
    "SelfEvaluationAdapter",
    "StageResult",
    "StreamCoordinator",
    "StreamingContext",
    "TimeoutManager",
    "UnknownEngineError",
    "WhyAdapter",
]
