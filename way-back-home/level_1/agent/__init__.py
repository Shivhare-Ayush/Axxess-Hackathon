"""
Clinical Diagnostic Assistant - Multi-Agent System

This package contains the multi-agent system for patient intake analysis:
- Root orchestrator (ClinicalOrchestratorAI) with before_agent_callback
- Parallel diagnostic crew (DiagnosticCrew)
- Specialist agents (ClinicalScribe, RadiologyAnalyst, RecordsAnalyst)

Key ADK Patterns Used:
1. before_agent_callback: Fetches patient config and sets state
2. {key} State Templating: Sub-agents access state via {audio_url}, {image_url}, etc.
3. ToolContext: Tools access state via tool_context.state.get()
4. ParallelAgent: Runs specialists concurrently
"""

from agent.agent import root_agent

__all__ = ["root_agent"]