from google.adk.tools import Tool
from agent.services.icd_service import ICDService

icd_service = ICDService()

def icd_lookup_tool(query: str):
    results = icd_service.search_icd(query)

    simplified = []

    for item in results.get("destinationEntities", [])[:5]:
        simplified.append({
            "code": item.get("theCode"),
            "title": item.get("title")
        })

    return simplified


icd_lookup = Tool(
    name="icd_lookup",
    description="Search ICD-11 codes for a medical condition or symptom.",
    func=icd_lookup_tool,
)
