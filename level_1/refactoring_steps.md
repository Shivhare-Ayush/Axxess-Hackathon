# Refactoring Steps: Way Back Home → Diagnostic Assistant

This document is a file-by-file guide for pivoting Level 1 from the alien-biome codelab into the healthcare Diagnostic Assistant. No Python source files have been modified yet — this is the implementation roadmap.

---

## Phase A: Deletions

Remove all alien-domain logic. These files have no healthcare analog.

| File | Reason |
|------|--------|
| `agent/agents/geological_analyst.py` | Soil/biome image analysis — no clinical equivalent |
| `agent/agents/botanical_analyst.py` | Flora/video analysis — no clinical equivalent |
| `agent/agents/astronomical_analyst.py` | Star-catalog triangulation + OneMCP BigQuery — no clinical equivalent |
| `agent/tools/star_tools.py` | `extract_star_features` FunctionTool + OneMCP BigQuery OAuth setup — space-specific |
| `setup/setup_star_catalog.py` | Creates BigQuery `way_back_home.star_catalog` — alien domain |
| `generate_evidence.py` | Generates soil/flora/star evidence via Gemini + Veo — alien domain |

---

## Phase B: Modifications for Agent 1 — The Clinical Scribe

### `agent/agents/geological_analyst.py` → DELETE + CREATE `agent/agents/clinical_scribe.py`

**New file: `agent/agents/clinical_scribe.py`**

- `Agent(name="ClinicalScribe", model="gemini-2.5-flash")`
- **Instruction** (two-step workflow):
  1. If `{audio_url}` is present → call `transcribe_audio_tool` first to get a text transcript
  2. Run NER on the transcript (or `{clinical_notes}` if no audio) to extract: vitals, symptoms, subjective complaints
  3. Call `map_icd_codes` via the ICD MCP toolset with the extracted condition list
  4. Return a structured dict: `{transcript, symptoms, icd_codes, confidence}`
- **Tools**: `transcribe_audio_tool` (FunctionTool) + `get_icd_mcp_toolset()` (MCPToolset)
- **State inputs**: `{audio_url}` and/or `{clinical_notes}` (ADK state templating)

---

### `agent/tools/mcp_tools.py` — MODIFY

- Remove: `get_geological_tool()` and `get_botanical_tool()`
- Rename: env var from `MCP_SERVER_URL` → `ICD_MCP_SERVER_URL`
- Rename: Cloud Run service reference from `location-analyzer` → `clinical-coder`
- Add: `get_icd_mcp_toolset()` — same `MCPToolset` + `StreamableHTTPConnectionParams` pattern, pointing to `{ICD_MCP_SERVER_URL}/mcp`

---

### `agent/tools/star_tools.py` → DELETE + CREATE `agent/tools/speech_tools.py`

**New file: `agent/tools/speech_tools.py`**

- Single `FunctionTool`: `transcribe_audio(audio_url: str) -> dict`
- **Implementation**: fetch audio bytes from GCS (`gs://` URL), pass as inline audio part to `gemini-2.5-flash` with a transcription prompt — mirrors the `extract_star_features` pattern (local Gemini call, no extra service)
- Returns: `{transcript: str, confidence: float, duration_seconds: float}`
- No OneMCP BigQuery dependency; no OAuth setup needed

---

### `agent/tools/confirm_tools.py` → MODIFY (rename to `agent/tools/diagnosis_tools.py`)

- **Remove**:
  - `BIOME_TO_QUADRANT` mapping dict
  - `_get_actual_biome()` helper
  - Coordinate-based validation logic (`x`, `y`)
  - Beacon activation logic
- **Keep**:
  - `ToolContext` import and usage pattern
  - `tool_context.state.get(...)` lookups (update keys: `participant_id` → `patient_id`)
  - `backend_url` fallback to env var
- **Add**: `submit_diagnosis(icd_codes: list, clinical_summary: str, tool_context: ToolContext) -> dict`
  - Reads `patient_id` and `backend_url` from `tool_context.state`
  - Makes `POST /diagnoses` to the healthcare backend (was `PATCH /participants/{id}/location`)
  - Returns `{status, diagnosis_id, timestamp}`

---

### `agent/agent.py` — MODIFY

**Renames:**
- `MissionAnalysisAI` → `ClinicalOrchestratorAI`
- `EvidenceAnalysisCrew` (ParallelAgent) → `DiagnosticCrew`
- `setup_participant_context` callback → `setup_patient_context`

**Import changes:**
- Remove: `geological_analyst`, `botanical_analyst`, `astronomical_analyst`
- Remove: `confirm_location_tool`
- Add: `clinical_scribe`, `radiology_analyst`, `records_analyst`
- Add: `submit_diagnosis_tool`

**`before_agent_callback` state keys:**
- Remove: `soil_url`, `flora_url`, `stars_url`, `x`, `y`
- Add: `audio_url`, `image_url`, `patient_id`, `clinical_notes`
- Keep: `project_id`, `backend_url`

**Root agent instruction update:**
- Remove: biome reference table, 2-of-3 consensus logic, quadrant mapping
- Add: synthesis workflow — collect 3 structured outputs → produce:
  - Preliminary diagnostic hypothesis
  - Auto-tagged ICD-11 codes
  - Structured EMR entry
  - Jargon-free "Recovery Plan" patient summary
- Swap final tool call: `confirm_location_tool` → `submit_diagnosis_tool`

---

### `agent/agents/__init__.py` — MODIFY

Replace exports:

```
# Remove:
geological_analyst, botanical_analyst, astronomical_analyst

# Add:
clinical_scribe, radiology_analyst, records_analyst
```

---

### `agent/tools/__init__.py` — MODIFY

Replace exports:

```
# Remove:
get_geological_tool, get_botanical_tool,
extract_star_features_tool, get_bigquery_mcp_toolset,
confirm_location_tool

# Add:
get_icd_mcp_toolset, transcribe_audio_tool, submit_diagnosis_tool
```

---

### `mcp-server/main.py` — MODIFY

- **Remove**: `GEOLOGICAL_PROMPT`, `analyze_geological()`, `BOTANICAL_PROMPT`, `analyze_botanical()`
- **Keep**: FastMCP init, Gemini client init, `parse_json_response()` utility
- **Add**:

```python
@mcp.tool()
def map_icd_codes(conditions: list[str]) -> dict:
    """Map extracted clinical conditions to ICD-11 codes."""
    # Uses simple-icd-11 library for lookups
    # Returns: {codes: [{condition, icd11_code, description}], mapped_count}
```

- **Update** server name: `"Location Analyzer MCP Server 🛸"` → `"Clinical Coder MCP Server 🏥"`

---

### `mcp-server/requirements.txt` — MODIFY

Add dependency:

```
simple-icd-11
```

---

### `pyproject.toml` — MODIFY

- `name`: `waybackhome-level1` → `diagnostic-assistant`
- `description`: update to reflect healthcare purpose
- **Remove** from dependencies: `google-cloud-bigquery`, `Pillow` (no longer needed)

---

### `setup/setup_env.sh` — MODIFY

- Remove: BigQuery API enablement (`bigquery.googleapis.com`)
- Remove: star catalog setup steps and references
- Remove: `PARTICIPANT_ID` export
- Add: `PATIENT_ID` export placeholder
- Rename: Cloud Run service references `location-analyzer` → `clinical-coder`
- Keep: Vertex AI, Cloud Run, Cloud Build, Artifact Registry, IAM setup

---

## Files NOT Changing

| File | Reason |
|------|--------|
| `config_utils.py` | Config loading logic is domain-agnostic and reusable as-is |
| `mcp-server/Dockerfile` | Python 3.11-slim base; no changes needed |
| `mcp-server/cloudbuild.yaml` | Update service name substitution only: `location-analyzer` → `clinical-coder` |

---

## Verification Checklist

After implementing all changes:

- [ ] `uv sync` completes without error
- [ ] `adk web` starts; sending a test patient query routes to `DiagnosticCrew`
- [ ] `ClinicalScribe` calls `transcribe_audio_tool` first, then MCP `map_icd_codes`
- [ ] `RadiologyAnalyst` calls MCP `analyze_imaging` and returns structured visual report
- [ ] `RecordsAnalyst` calls `rag_query` and returns patient history flags
- [ ] Root agent synthesizes all 3 outputs and calls `submit_diagnosis_tool`
- [ ] MCP server (`clinical-coder`) responds with valid ICD-11 code JSON
- [ ] `POST /diagnoses` backend call returns `{status: "ok", diagnosis_id: ...}`
