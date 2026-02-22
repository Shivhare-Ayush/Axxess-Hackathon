import os
import requests
import time

ICD_TOKEN_URL = "https://icdaccessmanagement.who.int/connect/token"
ICD_API_BASE = "https://id.who.int/icd/release/11/2024-01/mms"

class ICDService:
    def __init__(self):
        self.client_id = os.environ.get("ICD_CLIENT_ID")
        self.client_secret = os.environ.get("ICD_CLIENT_SECRET")
        self.token = None
        self.token_expiry = 0

    def _get_token(self):
        if self.token and time.time() < self.token_expiry:
            return self.token

        response = requests.post(
            ICD_TOKEN_URL,
            data={
                "grant_type": "client_credentials",
                "client_id": self.client_id,
                "client_secret": self.client_secret,
                "scope": "icdapi_access"
            },
        )

        response.raise_for_status()
        token_data = response.json()

        self.token = token_data["access_token"]
        self.token_expiry = time.time() + token_data["expires_in"] - 60
        return self.token

    def search_icd(self, query):
        token = self._get_token()

        headers = {
            "Authorization": f"Bearer {token}",
            "Accept": "application/json",
            "Accept-Language": "en",
        }

        response = requests.get(
            f"{ICD_API_BASE}/search",
            headers=headers,
            params={"q": query}
        )

        response.raise_for_status()
        return response.json()