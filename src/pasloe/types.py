"""Event type constants shared across Supervisor, Agent, and EventStore."""

# System lifecycle
GENESIS = "genesis"
JOB_FAILURE = "job_failure"

# Agent lifecycle
AGENT_START = "agent_start"
AGENT_END = "agent_end"
TURN_START = "turn_start"
TURN_END = "turn_end"
MAX_TURNS_REACHED = "max_turns_reached"

# Tool / LLM events (fine-grained agent logs — Supervisor does NOT use these to dispatch)
LLM_RESPONSE = "llm_response"
TOOL_EXEC_START = "tool_exec_start"
TOOL_EXEC_END = "tool_exec_end"

# Generational succession
CI_RESULT = "ci_result"
GENERATION_EVALUATION = "generation_evaluation"
GENERATION_HANDOFF = "generation_handoff"
GENERATION_REJECTED = "generation_rejected"

# External inputs
EXTERNAL_STIMULUS = "external_stimulus"

# Events that Supervisor should NOT dispatch on (Agent internal logs)
AGENT_INTERNAL_EVENTS: frozenset[str] = frozenset({
    AGENT_START,
    AGENT_END,
    TURN_START,
    TURN_END,
    MAX_TURNS_REACHED,
    LLM_RESPONSE,
    TOOL_EXEC_START,
    TOOL_EXEC_END,
    GENERATION_EVALUATION,  # Supervisor reacts to this via arbiter, not by launching new job
    GENERATION_REJECTED,
})
