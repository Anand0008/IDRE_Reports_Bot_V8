from typing import Optional, List, Any, Dict
from typing_extensions import TypedDict


class GraphState(TypedDict):
    """State object that flows through the LangGraph pipeline — V6."""
    user_query: str
    session_id: str

    # Access control
    user_role: str              # 'MA' | 'PA' | 'PS' | 'AC' | 'AM' | 'CB' | 'VT' | 'VO' | 'DQD'
    permitted_tables: List[str] # resolved from access_control.json by Context Loader

    # Session memory
    conversation_history: List[Dict[str, str]]  # [{query, summary}, ...] last N turns
    resolved_query: str                         # user_query after pronoun/reference expansion

    # V6: Entity registry for context loader
    entity_registry: Dict[str, str]

    # Schema mapping
    relevant_tables: List[str]
    schema_context: str

    # Platform knowledge context (injected by platform_context_agent)
    platform_context: str

    # SQL generation
    generated_sql: str
    validated_sql: str

    # Execution
    query_result: Optional[List[Dict[str, Any]]]
    row_count: int
    execution_error: Optional[str]

    # Ambiguity scoring
    ambiguity_score: float
    ambiguity_flags: List[str]

    # Business Glossary
    glossary_matches: List[Dict[str, Any]]

    # Clarification
    needs_clarification: bool
    clarification_question: str
    clarification_attempted: bool

    # Response
    formatted_response: str
    assumptions: List[str]
    response_format: str
    chart_config: Optional[Dict[str, Any]]
    query_explanation: str
    query_narrative: str
    proactive_suggestions: List[str]

    # Pipeline control
    retry_count: int
    error_message: str
    retry_context: str

    # V6: Query complexity scoring
    query_complexity: Optional[Dict[str, Any]]

    # Audit / timing
    pipeline_start_ms: int
    agent_timings: Dict[str, int]

    # Token usage
    token_usage: Dict[str, Any]

    # Structured trace
    agent_trace: List[Dict[str, Any]]

    # Feedback & Reproducibility
    user_identity: str
    feedback_correction_context: Optional[Dict[str, Any]]
    is_feedback_retry: bool
    feedback_record_id: str

    # V6: User preferences
    user_preferences: Optional[Dict[str, Any]]

    # V6: SQL self-verification result
    self_verification: Optional[Dict[str, Any]]

    # V6: EXPLAIN plan preview
    explain_plan: Optional[Dict[str, Any]]
