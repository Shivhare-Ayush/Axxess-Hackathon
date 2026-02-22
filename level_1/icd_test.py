import os
import requests

# Make sure your ICD credentials are exported in the shell
# export ICD_CLIENT_ID="your_client_id"
# export ICD_CLIENT_SECRET="your_client_secret"

CLIENT_ID = os.environ.get("ICD_CLIENT_ID")
CLIENT_SECRET = os.environ.get("ICD_CLIENT_SECRET")

if not CLIENT_ID or not CLIENT_SECRET:
    raise ValueError("ICD_CLIENT_ID and ICD_CLIENT_SECRET must be set as environment variables.")

# Step 1: Get access token
token_url = "https://icdaccessmanagement.who.int/connect/token"
data = {
    "grant_type": "client_credentials",
    "client_id": CLIENT_ID,
    "client_secret": CLIENT_SECRET,
    "scope": "icdapi_access"
}

token_resp = requests.post(token_url, data=data)
token_resp.raise_for_status()  # Raise error if request fails
access_token = token_resp.json()["access_token"]
print("Access token fetched successfully!")

# Step 2: Search ICD-11
def search_icd(query):
    url = f"https://id.who.int/icd/release/11/2024-01/mms/search?q={query}"
    headers = {"Authorization": f"Bearer {access_token}"}
    resp = requests.get(url, headers=headers)
    resp.raise_for_status()
    return resp.json()

# Example usage
result = search_icd("Type 2 diabetes")
print(result)