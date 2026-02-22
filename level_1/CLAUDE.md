# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Overview

A **Clinical Diagnostic Assistant** built on Google ADK — a multi-agent system that accepts multi-modal patient intake (audio consultation, medical imaging, patient EMR history) and produces a preliminary diagnosis, ICD-11 codes, a structured EMR entry, and a jargon-free patient summary. The agent uses **Google ADK**, a custom FastMCP server for ICD-11 code mapping, and a local RAG tool for patient history retrieval.

## Environment Setup

Before developing, source the generated environment file:

```bash
source ../set_env.sh  # sets GOOGLE_CLOUD_PROJECT, PATIENT_ID, ICD_MCP_SERVER_URL, etc.
```

Run the initial setup (only once per project):

```bash
bash setup/setup_env.sh          # enables GCP APIs, creates service account, writes set_env.sh
```

## Running the Agent

```bash
# Install dependencies (uv is the package manager)
uv sync

# Run locally with ADK web UI
adk web

# Or run via ADK CLI
adk run agent
```

## Deploying the MCP Server

```bash
cd mcp-server
gcloud builds submit --config cloudbuild.yaml \
  --substitutions=_SERVICE_ACCOUNT=$SERVICE_ACCOUNT,_REGION=$REGION,_REPO_NAME=$REPO_NAME

# After deploy, update ICD_MCP_SERVER_URL env var:
export ICD_MCP_SERVER_URL=$(gcloud run services describe clinical-coder --region $REGION --format='value(status.url)')
```

## Architecture

### Data Flow

```
User query (audio_url + image_url + patient_id)
  → Root Agent / ClinicalOrchestratorAI
      (before_agent_callback fetches patient data from backend API)
  → Sets state: audio_url, image_url, patient_id, clinical_notes, etc.
  → DiagnosticCrew (ParallelAgent) runs 3 specialists concurrently:
      ├─ ClinicalScribe     → transcribe_audio_tool (local Gemini) → Custom MCP → map_icd_codes()
      ├─ RadiologyAnalyst   → Custom MCP (Cloud Run) → analyze_imaging(image_url)
      └─ RecordsAnalyst     → FunctionTool: rag_query(patient_id)  [local RAG call]
  → Root Agent synthesizes 3 outputs:
      - Preliminary diagnostic hypothesis
      - Auto-tagged ICD-11 codes
      - Structured EMR entry
      - Jargon-free patient "Recovery Plan" summary
  → submit_diagnosis_tool (reads state via ToolContext) → POST to healthcare backend
```

### Key Files

| File | Purpose |
|------|---------|
| `agent/agent.py` | Root orchestrator (`ClinicalOrchestratorAI`); `before_agent_callback` fetches patient state |
| `agent/agents/clinical_scribe.py` | Specialist: transcribe audio → NER → ICD-11 code mapping via MCP |
| `agent/agents/radiology_analyst.py` | Specialist: medical imaging analysis via custom MCP |
| `agent/agents/records_analyst.py` | Specialist: patient history RAG query against MIMIC-IV vector DB |
| `agent/tools/mcp_tools.py` | `MCPToolset` connection to the `clinical-coder` MCP server |
| `agent/tools/speech_tools.py` | Local `transcribe_audio` FunctionTool (Gemini native audio) |
| `agent/tools/diagnosis_tools.py` | `submit_diagnosis` tool; reads state via `ToolContext`; POST to healthcare backend |
| `mcp-server/main.py` | FastMCP server with `map_icd_codes` tool (uses `simple-icd-11` library) |
| `config_utils.py` | Config loader — prefers env vars + backend API (Cloud Run), falls back to `config.json` |

### ADK Patterns Used

**`before_agent_callback`** (`agent/agent.py`): Runs once at agent startup. Fetches patient data from the backend API using `PATIENT_ID` and `BACKEND_URL`, then populates `callback_context.state` so all sub-agents can access the patient record and evidence URLs.

**`{key}` State Templating**: Sub-agent instructions use `{audio_url}`, `{image_url}`, `{patient_id}`, `{clinical_notes}` etc. ADK substitutes values from state automatically — no manual passing required.

**`ToolContext`** (`diagnosis_tools.py`): Tools access shared state (patient_id, backend_url) via `tool_context.state.get(...)`, falling back to environment variables.

**Two MCP Patterns**:
- *Custom MCP*: `StreamableHTTPConnectionParams` to `{ICD_MCP_SERVER_URL}/mcp` (your Cloud Run server, uses `fastmcp`)
- *Local RAG*: FunctionTool wrapping a vector DB query (no MCP needed; runs in-process)

**`ParallelAgent`**: Wraps the three specialist agents to run them concurrently inside `DiagnosticCrew`.

### Clinical Domain Table

ICD-11 specialty areas mapped to agent responsibilities:

| Specialty | Agent | Input | Output |
|-----------|-------|-------|--------|
| Audio/Text NLP | ClinicalScribe | `audio_url`, `clinical_notes` | ICD-11 codes, structured symptoms |
| Radiology / Imaging | RadiologyAnalyst | `image_url` | Visual anomaly report + confidence |
| EMR / Patient History | RecordsAnalyst | `patient_id` | Historical risks, allergies, chronic conditions |

### MCP Server (`mcp-server/main.py`)

Built with `fastmcp`. One tool:
- `map_icd_codes(conditions: list[str])`: uses `simple-icd-11` library to look up codes, returns `{codes: [{condition, icd11_code, description}], mapped_count}`

Deployed to Cloud Run; `PORT` env var controls listen port (default 8080).

### Patient RAG Store

Vector database seeded with MIMIC-IV patient records. The `RecordsAnalyst` queries this store with the `patient_id` to surface historical risks, drug interactions, and chronic condition flags relevant to the current encounter.

## Environment Variables

| Variable | Description |
|----------|-------------|
| `GOOGLE_CLOUD_PROJECT` | GCP project ID |
| `GOOGLE_GENAI_USE_VERTEXAI` | Must be `true` for Vertex AI access |
| `PATIENT_ID` | Patient identifier for the current encounter |
| `BACKEND_URL` | Healthcare backend API endpoint |
| `ICD_MCP_SERVER_URL` | URL of the deployed clinical-coder Cloud Run service |
| `REGION` | GCP region (default: `us-central1`) |
