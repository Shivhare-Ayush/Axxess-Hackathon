#!/bin/bash
#
# Way Back Home - Setup Script
#
# This script connects you to the Way Back Home rescue network
# and reserves your explorer identity.
#
# Run from project root: ./scripts/setup.sh
#

set -e

# Determine project root (parent of scripts directory)
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(dirname "$SCRIPT_DIR")"

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
CYAN='\033[0;36m'
NC='\033[0m' # No Color

# Load configuration from workshop.config.json
WORKSHOP_CONFIG="${PROJECT_ROOT}/workshop.config.json"

if [ ! -f "$WORKSHOP_CONFIG" ]; then
    echo -e "${RED}Error: workshop.config.json not found.${NC}"
    exit 1
fi

# Parse URLs from config file
API_BASE=$(python3 -c "import json; print(json.load(open('${WORKSHOP_CONFIG}'))['api_base_url'])" 2>/dev/null)
MAP_BASE_URL=$(python3 -c "import json; print(json.load(open('${WORKSHOP_CONFIG}'))['map_base_url'])" 2>/dev/null)

if [ -z "$API_BASE" ]; then
    echo -e "${RED}Error: Could not read api_base_url from workshop.config.json${NC}"
    exit 1
fi

CONFIG_FILE="${PROJECT_ROOT}/config.json"

# Print banner
echo ""
echo -e "${CYAN}🚀 Welcome to Way Back Home!${NC}"
echo ""

# =============================================================================
# Step 0: Check Google Cloud Authentication
# =============================================================================
echo "Checking Google Cloud authentication..."

if ! gcloud auth print-access-token > /dev/null 2>&1; then
    echo -e "${RED}Error: Not authenticated with Google Cloud.${NC}"
    echo "Please run: gcloud auth login"
    exit 1
fi

echo -e "${GREEN}✓ Authenticated${NC}"

# =============================================================================
# Step 1: Find or Create Google Cloud Project
# =============================================================================
PROJECT_FILE="$HOME/project_id.txt"
PROJECT_ID=""

# NEW START: Delete existing project file to ensure a clean state
rm -f "$PROJECT_FILE"

# 1c. Interactive project creation if no project found
if [ -z "$PROJECT_ID" ]; then
    echo ""
    echo -e "${YELLOW}Let's set a new project.${NC}"

    CODELAB_PROJECT_PREFIX="waybackhome"
    PREFIX_LEN=${#CODELAB_PROJECT_PREFIX}
    MAX_SUFFIX_LEN=$(( 30 - PREFIX_LEN - 1 ))
    RANDOM_SUFFIX=$(LC_ALL=C tr -dc 'a-z0-9' < /dev/urandom | head -c "$MAX_SUFFIX_LEN")
    RANDOM_PROJECT_ID="${CODELAB_PROJECT_PREFIX}-${RANDOM_SUFFIX}"

    while true; do
        echo ""
        echo "Select a Project ID:"
        echo "  1. Press Enter to CREATE a new project: $RANDOM_PROJECT_ID"
        echo "  2. Or type an existing Project ID to use."
        read -p "Project ID: " USER_INPUT

        TARGET_ID="${USER_INPUT:-$RANDOM_PROJECT_ID}"

        if [ -z "$TARGET_ID" ]; then
            echo -e "${RED}Project ID cannot be empty.${NC}"
            continue
        fi

        echo "Checking status of '$TARGET_ID'..."

        if gcloud projects describe "$TARGET_ID" >/dev/null 2>&1; then
            echo -e "${GREEN}✓ Project '$TARGET_ID' exists and is accessible.${NC}"
            PROJECT_ID="$TARGET_ID"
            break
        else
            echo "Project '$TARGET_ID' not found. Attempting to create..."
            if gcloud projects create "$TARGET_ID" --quiet; then
                echo -e "${GREEN}✓ Successfully created project '$TARGET_ID'.${NC}"
                PROJECT_ID="$TARGET_ID"
                break
            else
                echo -e "${RED}Failed to create '$TARGET_ID'. Please try a different ID.${NC}"
            fi
        fi
    done

    gcloud config set project "$PROJECT_ID" --quiet || {
        echo -e "${RED}Failed to set active project.${NC}"
        exit 1
    }
fi

# Save project ID for reuse across levels
echo "$PROJECT_ID" > "$PROJECT_FILE"
echo -e "Using project: ${CYAN}${PROJECT_ID}${NC}"

# =============================================================================
# Step 2: Check and Enable Billing (NEW!)
# =============================================================================
echo ""
echo -e "${YELLOW}Checking billing configuration...${NC}"

# Pre-install billing library (needed by billing-enablement.py)
pip install --quiet --user google-cloud-billing 2>/dev/null || true

# Run the billing enablement script
if ! python3 "${SCRIPT_DIR}/billing-enablement.py"; then
    echo ""
    echo -e "${RED}Billing setup incomplete. Please configure billing and try again.${NC}"
    exit 1
fi

# =============================================================================
# Step 3: Enable Required APIs
# =============================================================================
echo ""
echo -e "${YELLOW}Enabling required APIs...${NC}"

# Enable Vertex AI API (required for Level 0)
gcloud services enable aiplatform.googleapis.com --quiet 2>/dev/null || {
    echo -e "${RED}Failed to enable Vertex AI API.${NC}"
    echo "This may be a billing or permissions issue."
    exit 1
}

echo -e "${GREEN}✓ Vertex AI API enabled${NC}"

# =============================================================================
# Step 4: Get event code
# =============================================================================
echo ""
echo -e "Enter event code (from QR/slide)."
echo -e "If you're learning on your own, enter ${YELLOW}sandbox${NC} to join the public learning environment."
echo ""
read -p "Event code: " EVENT_CODE

if [ -z "$EVENT_CODE" ]; then
    echo -e "${RED}Error: Event code is required.${NC}"
    exit 1
fi

# Trim whitespace
EVENT_CODE=$(echo "$EVENT_CODE" | xargs)

# =============================================================================
# Step 5: Validate event
# =============================================================================
echo "Validating event..."

EVENT_RESPONSE=$(curl -s -w "\n%{http_code}" "${API_BASE}/events/${EVENT_CODE}")
HTTP_CODE=$(echo "$EVENT_RESPONSE" | tail -n1)
EVENT_BODY=$(echo "$EVENT_RESPONSE" | sed '$d')

if [ "$HTTP_CODE" != "200" ]; then
    echo -e "${RED}✗ Event not found.${NC}"
    echo ""
    echo "Please check your event code and try again."
    echo "If you're learning on your own, use: sandbox"
    exit 1
fi

# Parse event name from response
EVENT_NAME=$(echo "$EVENT_BODY" | python3 -c "import sys,json; print(json.load(sys.stdin).get('name', 'Unknown Event'))" 2>/dev/null || echo "Unknown Event")

echo -e "${GREEN}✓ Connected to: ${EVENT_NAME}${NC}"
echo ""

# =============================================================================
# Step 6: Get username
# =============================================================================
while true; do
    read -p "Choose your explorer name: " USERNAME

    if [ -z "$USERNAME" ]; then
        echo -e "${RED}Username cannot be empty.${NC}"
        continue
    fi

    # Trim whitespace and validate format
    USERNAME=$(echo "$USERNAME" | xargs)

    # Check for valid characters (alphanumeric, underscores, hyphens)
    if ! [[ "$USERNAME" =~ ^[a-zA-Z0-9_-]+$ ]]; then
        echo -e "${RED}Username can only contain letters, numbers, underscores, and hyphens.${NC}"
        continue
    fi

    # Check length
    if [ ${#USERNAME} -lt 2 ] || [ ${#USERNAME} -gt 20 ]; then
        echo -e "${RED}Username must be 2-20 characters long.${NC}"
        continue
    fi

    # Check availability
    AVAIL_RESPONSE=$(curl -s -w "\n%{http_code}" "${API_BASE}/events/${EVENT_CODE}/check-username/${USERNAME}")
    AVAIL_CODE=$(echo "$AVAIL_RESPONSE" | tail -n1)
    AVAIL_BODY=$(echo "$AVAIL_RESPONSE" | sed '$d')

    if [ "$AVAIL_CODE" != "200" ]; then
        echo -e "${RED}Error checking username availability. Please try again.${NC}"
        continue
    fi

    IS_AVAILABLE=$(echo "$AVAIL_BODY" | python3 -c "import sys,json; print(json.load(sys.stdin).get('available', False))" 2>/dev/null || echo "false")

    if [ "$IS_AVAILABLE" == "True" ] || [ "$IS_AVAILABLE" == "true" ]; then
        echo -e "${GREEN}✓ Username available!${NC}"
        break
    else
        echo -e "${YELLOW}⚠️  That name is taken. Try another.${NC}"
    fi
done

echo ""
echo "Initializing your explorer profile..."

# =============================================================================
# Step 7: Reserve identity and get participant details
# =============================================================================
INIT_RESPONSE=$(curl -s -w "\n%{http_code}" -X POST "${API_BASE}/participants/init" \
    -H "Content-Type: application/json" \
    -d "{\"event_code\": \"${EVENT_CODE}\", \"username\": \"${USERNAME}\"}")

INIT_CODE=$(echo "$INIT_RESPONSE" | tail -n1)
INIT_BODY=$(echo "$INIT_RESPONSE" | sed '$d')

if [ "$INIT_CODE" != "200" ] && [ "$INIT_CODE" != "201" ]; then
    echo -e "${RED}✗ Failed to initialize profile.${NC}"
    ERROR_MSG=$(echo "$INIT_BODY" | python3 -c "import sys,json; print(json.load(sys.stdin).get('detail', 'Unknown error'))" 2>/dev/null || echo "Unknown error")
    echo "Error: $ERROR_MSG"
    exit 1
fi

# Parse response
PARTICIPANT_ID=$(echo "$INIT_BODY" | python3 -c "import sys,json; print(json.load(sys.stdin)['participant_id'])" 2>/dev/null)
STARTING_X=$(echo "$INIT_BODY" | python3 -c "import sys,json; print(json.load(sys.stdin)['starting_x'])" 2>/dev/null)
STARTING_Y=$(echo "$INIT_BODY" | python3 -c "import sys,json; print(json.load(sys.stdin)['starting_y'])" 2>/dev/null)

if [ -z "$PARTICIPANT_ID" ]; then
    echo -e "${RED}✗ Failed to parse server response.${NC}"
    exit 1
fi

# =============================================================================
# Step 8: Write config.json
# =============================================================================
cat > "$CONFIG_FILE" << EOF
{
    "event_code": "${EVENT_CODE}",
    "event_name": "${EVENT_NAME}",
    "username": "${USERNAME}",
    "participant_id": "${PARTICIPANT_ID}",
    "starting_x": ${STARTING_X},
    "starting_y": ${STARTING_Y},
    "api_base": "${API_BASE}",
    "map_base_url": "${MAP_BASE_URL}",
    "project_id": "${PROJECT_ID}"
}
EOF

echo ""
echo -e "${GREEN}✓ Environment configured!${NC}"
echo -e "  Explorer ID: ${CYAN}${PARTICIPANT_ID}${NC}"
echo -e "  Starting coordinates: ${CYAN}(${STARTING_X}, ${STARTING_Y})${NC}"
echo ""
echo -e "Next: ${YELLOW}cd level_0 && python customize.py${NC}"