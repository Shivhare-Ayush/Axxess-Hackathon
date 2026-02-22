#!/bin/bash
# =============================================================================
# Level 1: Environment Setup Script
# =============================================================================
# This script enables the necessary APIs and IAM permissions for Level 1:
# - Vertex AI (for Gemini)
# - Cloud Run (for MCP server and agent deployment)
# - Service accounts and IAM bindings
#
# Run this ONCE before starting Level 1.
# =============================================================================

set -e

# Get Google Cloud Project ID (check multiple sources)
PROJECT_ID=$(gcloud config get-value project 2>/dev/null)
if [ "$PROJECT_ID" = "(unset)" ]; then PROJECT_ID=""; fi

# Fallback: check project_id.txt saved by setup.sh (persists across Cloud Shell sessions)
if [ -z "$PROJECT_ID" ] && [ -s "$HOME/project_id.txt" ]; then
    PROJECT_ID=$(cat "$HOME/project_id.txt" | tr -d '[:space:]')
    if [ -n "$PROJECT_ID" ]; then
        echo "📋 Restored project from project_id.txt: $PROJECT_ID"
        gcloud config set project "$PROJECT_ID" --quiet 2>/dev/null
    fi
fi

if [ -z "$PROJECT_ID" ]; then
    echo "❌ Could not determine Google Cloud Project ID."
    echo "   Please run: gcloud config set project <PROJECT_ID>"
    exit 1
fi

echo "================================================================"
echo "Level 1: Environment Setup"
echo "================================================================"
echo "Project: $PROJECT_ID"
echo ""

# -----------------------------------------------------------------------------
# Step 1: Enable Core APIs
# -----------------------------------------------------------------------------
echo "[1/4] Enabling core Google Cloud APIs..."

gcloud services enable aiplatform.googleapis.com --project=$PROJECT_ID
echo "      ✓ Vertex AI API enabled"

gcloud services enable run.googleapis.com --project=$PROJECT_ID
echo "      ✓ Cloud Run API enabled"

gcloud services enable cloudbuild.googleapis.com --project=$PROJECT_ID
echo "      ✓ Cloud Build API enabled"

gcloud services enable artifactregistry.googleapis.com --project=$PROJECT_ID
echo "      ✓ Artifact Registry API enabled"

gcloud services enable iam.googleapis.com --project=$PROJECT_ID
echo "      ✓ IAM API enabled"

# -----------------------------------------------------------------------------
# Step 2: Create Service Account and IAM Permissions
# -----------------------------------------------------------------------------
echo ""
echo "[2/4] Setting up service account and IAM permissions..."

SA_NAME="way-back-home-sa"
SERVICE_ACCOUNT="${SA_NAME}@${PROJECT_ID}.iam.gserviceaccount.com"

# Create service account if it doesn't exist
if gcloud iam service-accounts describe $SERVICE_ACCOUNT --project=$PROJECT_ID >/dev/null 2>&1; then
    echo "      ✓ Service account '$SA_NAME' already exists"
else
    gcloud iam service-accounts create $SA_NAME \
        --display-name="Way Back Home Workshop Service Account" \
        --project=$PROJECT_ID
    echo "      ✓ Service account '$SA_NAME' created"

    # Wait for identity propagation to prevent "Service account not found" errors
    echo "      ⏳ Waiting 10 seconds for identity propagation..."
    sleep 10
fi

# Grant Vertex AI User role (for Gemini)
echo "      Granting Vertex AI User role..."
gcloud projects add-iam-policy-binding $PROJECT_ID \
    --member="serviceAccount:$SERVICE_ACCOUNT" \
    --role="roles/aiplatform.user" \
    --condition=None \
    --quiet >/dev/null 2>&1
echo "      ✓ Vertex AI User role granted"

# Grant Cloud Run Invoker role (for service-to-service calls)
echo "      Granting Cloud Run Invoker role..."
gcloud projects add-iam-policy-binding $PROJECT_ID \
    --member="serviceAccount:$SERVICE_ACCOUNT" \
    --role="roles/run.invoker" \
    --condition=None \
    --quiet >/dev/null 2>&1
echo "      ✓ Cloud Run Invoker role granted"

# Grant Storage Object Viewer role (for Cloud Storage URLs in Gemini)
echo "      Granting Storage Object Viewer role..."
gcloud projects add-iam-policy-binding $PROJECT_ID \
    --member="serviceAccount:$SERVICE_ACCOUNT" \
    --role="roles/storage.objectViewer" \
    --condition=None \
    --quiet >/dev/null 2>&1
echo "      ✓ Storage Object Viewer role granted"

# -----------------------------------------------------------------------------
# Step 3: Configure Cloud Build IAM for Deployments
# -----------------------------------------------------------------------------
echo ""
echo "[3/4] Configuring Cloud Build IAM for deployments..."

# Robust retrieval of Project Number with retry
PROJECT_NUMBER=$(gcloud projects describe "${PROJECT_ID}" --format='value(projectNumber)' 2>/dev/null || true)

if [ -z "$PROJECT_NUMBER" ]; then
    echo "      ⚠️  First attempt to get Project Number failed. Retrying..."
    sleep 5
    PROJECT_NUMBER=$(gcloud projects describe "${PROJECT_ID}" --format='value(projectNumber)')
fi

# Default compute service account (used during Cloud Build steps)
COMPUTE_SA="${PROJECT_NUMBER}-compute@developer.gserviceaccount.com"

echo "      Compute SA: ${COMPUTE_SA}"

# Grant Compute SA permission to act as way-back-home-sa (for Cloud Run deploy)
echo "      Granting Compute SA permission to deploy as way-back-home-sa..."
gcloud iam service-accounts add-iam-policy-binding "${SERVICE_ACCOUNT}" \
    --member="serviceAccount:${COMPUTE_SA}" \
    --role="roles/iam.serviceAccountUser" \
    --project="${PROJECT_ID}" \
    --quiet >/dev/null 2>&1
echo "      ✓ Cloud Build can now deploy services as way-back-home-sa"

# Grant Compute SA Cloud Run Admin (required for deploy step)
echo "      Granting Compute SA Cloud Run Admin role..."
gcloud projects add-iam-policy-binding $PROJECT_ID \
    --member="serviceAccount:${COMPUTE_SA}" \
    --role="roles/run.admin" \
    --condition=None \
    --quiet >/dev/null 2>&1
echo "      ✓ Cloud Run Admin role granted to Compute SA"

# -----------------------------------------------------------------------------
# Step 4: Create Artifact Registry Repository + Write set_env.sh
# -----------------------------------------------------------------------------
echo ""
echo "[4/4] Creating Artifact Registry repository and environment file..."

REPO_NAME="way-back-home"
REGION="us-central1"

if gcloud artifacts repositories describe $REPO_NAME --location=$REGION --project=$PROJECT_ID >/dev/null 2>&1; then
    echo "      ✓ Repository '$REPO_NAME' already exists"
else
    gcloud artifacts repositories create $REPO_NAME \
        --repository-format=docker \
        --location=$REGION \
        --description="Way Back Home workshop container images" \
        --project=$PROJECT_ID
    echo "      ✓ Repository '$REPO_NAME' created"
fi

SCRIPT_DIR="$( cd "$( dirname "${BASH_SOURCE[0]}" )" && pwd )"
ENV_FILE="$SCRIPT_DIR/../../set_env.sh"
CONFIG_FILE="$SCRIPT_DIR/../../config.json"

# -----------------------------------------------------------------------------
# Extract PATIENT_ID from config.json
# -----------------------------------------------------------------------------
PATIENT_ID=""
if [ -f "$CONFIG_FILE" ]; then
    PATIENT_ID=$(python3 -c "import json; print(json.load(open('$CONFIG_FILE')).get('patient_id', ''))" 2>/dev/null || echo "")
    if [ -n "$PATIENT_ID" ]; then
        echo "      Found PATIENT_ID in config.json: $PATIENT_ID"
    else
        echo "      ⚠️  config.json exists but no patient_id found"
    fi
else
    echo "      ⚠️  config.json not found - PATIENT_ID will be empty"
fi

# -----------------------------------------------------------------------------
# Determine BACKEND_URL
# -----------------------------------------------------------------------------
BACKEND_ENV_FILE="$SCRIPT_DIR/../../dashboard/backend/.env"
DEFAULT_BACKEND_URL="https://api.healthcare.dev"

if [ -f "$BACKEND_ENV_FILE" ]; then
    BACKEND_URL=$(grep -E "^API_BASE_URL=" "$BACKEND_ENV_FILE" 2>/dev/null | cut -d'=' -f2- | tr -d '"' | tr -d "'" || echo "")
    if [ -n "$BACKEND_URL" ]; then
        echo "      Found BACKEND_URL in dashboard/backend/.env: $BACKEND_URL"
    fi
fi

if [ -z "$BACKEND_URL" ] && [ -f "$CONFIG_FILE" ]; then
    BACKEND_URL=$(python3 -c "import json; print(json.load(open('$CONFIG_FILE')).get('api_base', ''))" 2>/dev/null || echo "")
    if [ -n "$BACKEND_URL" ]; then
        echo "      Found BACKEND_URL in config.json: $BACKEND_URL"
    fi
fi

if [ -z "$BACKEND_URL" ]; then
    BACKEND_URL="$DEFAULT_BACKEND_URL"
    echo "      Using default BACKEND_URL: $BACKEND_URL"
fi

# -----------------------------------------------------------------------------
# Write set_env.sh
# -----------------------------------------------------------------------------
cat <<EOF > "$ENV_FILE"
#!/bin/bash
# =============================================================================
# Way Back Home: Environment Variables
# =============================================================================
# Generated by setup_env.sh on $(date)
# Source this file before running agents or deploying services.
# =============================================================================

# Google Cloud Configuration
export GOOGLE_CLOUD_PROJECT="$PROJECT_ID"
export PROJECT_ID="$PROJECT_ID"
export REGION="$REGION"
export GOOGLE_CLOUD_LOCATION="$REGION"

# ADK Configuration - Required for adk web and agent execution
export GOOGLE_GENAI_USE_VERTEXAI=true

# Patient Configuration
export PATIENT_ID="$PATIENT_ID"

# Backend API URL (for agent tools to submit diagnoses, fetch patient data)
export BACKEND_URL="$BACKEND_URL"

# Service Account for Cloud Run deployments
export SERVICE_ACCOUNT="$SERVICE_ACCOUNT"
export REPO_NAME="$REPO_NAME"

# These will be set after deploying services:
# export ICD_MCP_SERVER_URL="https://clinical-coder-xxx.a.run.app"
# export LEVEL1_AGENT_URL="https://clinical-orchestrator-xxx.a.run.app"

echo "Environment loaded for project: \$PROJECT_ID (Vertex AI mode)"
if [ -n "\$PATIENT_ID" ]; then
    echo "Patient ID: \$PATIENT_ID"
fi
EOF

chmod +x "$ENV_FILE"
echo "      ✓ Created $ENV_FILE"

# -----------------------------------------------------------------------------
# Summary
# -----------------------------------------------------------------------------
echo ""
echo "================================================================"
echo "✅ Environment Setup Complete!"
echo "================================================================"
echo ""
echo "Enabled APIs:"
echo "  • Vertex AI (Gemini)"
echo "  • Cloud Run (deployments)"
echo "  • Cloud Build (CI/CD)"
echo "  • Artifact Registry (container images)"
echo ""
echo "Service Account: $SERVICE_ACCOUNT"
echo "  Roles granted:"
echo "  • roles/aiplatform.user (Gemini access)"
echo "  • roles/run.invoker (Cloud Run service-to-service)"
echo "  • roles/storage.objectViewer (Read Cloud Storage)"
echo ""
echo "Cloud Build Configuration:"
echo "  Compute SA: $COMPUTE_SA"
echo "  • Can deploy Cloud Run services as way-back-home-sa"
echo "  • Has roles/run.admin for deployments"
echo ""
echo "Patient ID: ${PATIENT_ID:-"(not set - update config.json)"}"
echo "Backend URL: $BACKEND_URL"
echo ""
echo "ADK Configuration:"
echo "  • GOOGLE_GENAI_USE_VERTEXAI=true (uses Vertex AI for Gemini)"
echo "  • GOOGLE_CLOUD_LOCATION=$REGION"
echo ""
echo "Next steps:"
echo "  1. Source the environment: source \$HOME/way-back-home/set_env.sh"
echo "  2. Deploy the clinical-coder MCP server: cd mcp-server && gcloud builds submit ..."
echo "  3. Export ICD_MCP_SERVER_URL after deploy"
echo "  4. Run: adk web"
echo ""
