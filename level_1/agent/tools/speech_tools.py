"""
Speech Transcription Tool

Local FunctionTool that uses Gemini's native audio capabilities to transcribe
audio files stored in Cloud Storage.

Mirrors the extract_star_features pattern from the original codebase:
a local Gemini call via FunctionTool, no additional API or MCP server needed.
"""

import os
import json
import logging

from google import genai
from google.genai import types as genai_types
from google.adk.tools import FunctionTool

logger = logging.getLogger(__name__)

PROJECT_ID = os.environ.get("GOOGLE_CLOUD_PROJECT", "")

if not PROJECT_ID:
    logger.warning("[Speech Tools] GOOGLE_CLOUD_PROJECT not set")

genai_client = genai.Client(
    vertexai=True,
    project=PROJECT_ID or "placeholder",
    location=os.environ.get("GOOGLE_CLOUD_LOCATION", "us-central1")
)

logger.info(f"[Speech Tools] Initialized for project: {PROJECT_ID}")

TRANSCRIPTION_PROMPT = """Transcribe the following audio recording accurately.

Return ONLY valid JSON (no markdown, no explanation):
{
    "transcript": "full verbatim transcription of the audio",
    "confidence": 0.0,
    "duration_seconds": 0.0
}
"""


def _parse_json_response(text: str) -> dict:
    """Parse JSON from Gemini response, handling markdown formatting."""
    cleaned = text.strip()
    if cleaned.startswith("```json"):
        cleaned = cleaned[7:]
    elif cleaned.startswith("```"):
        cleaned = cleaned[3:]
    if cleaned.endswith("```"):
        cleaned = cleaned[:-3]
    cleaned = cleaned.strip()

    try:
        return json.loads(cleaned)
    except json.JSONDecodeError as e:
        logger.error(f"Failed to parse JSON: {e}")
        return {"error": f"Failed to parse response: {str(e)}"}


def transcribe_audio(audio_url: str) -> dict:
    """
    Transcribe an audio file from Cloud Storage using Gemini native audio.

    Fetches audio from a gs:// URL and passes it as an inline audio part
    to Gemini for transcription — no Speech-to-Text API required.

    Args:
        audio_url: Cloud Storage URL (gs://bucket/path/file.wav or .mp3)

    Returns:
        dict with transcript, confidence, and duration_seconds
    """
    logger.info(f"[Speech] Transcribing: {audio_url}")

    response = genai_client.models.generate_content(
        model="gemini-2.5-flash",
        contents=[
            TRANSCRIPTION_PROMPT,
            genai_types.Part.from_uri(file_uri=audio_url, mime_type="audio/wav")
        ]
    )

    result = _parse_json_response(response.text)
    logger.info(f"[Speech] Transcription complete, confidence={result.get('confidence')}")
    return result


transcribe_audio_tool = FunctionTool(transcribe_audio)
