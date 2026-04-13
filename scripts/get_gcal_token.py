"""
Run once to get a GCal token with write scope.
Usage: python3 scripts/get_gcal_token.py
Then paste the printed JSON into Supabase users.google_credentials.
"""
import json
from google_auth_oauthlib.flow import InstalledAppFlow

WRITE_SCOPES = [
    "https://www.googleapis.com/auth/calendar.events",
    "https://www.googleapis.com/auth/calendar.readonly",
]

flow = InstalledAppFlow.from_client_secrets_file("credentials.json", WRITE_SCOPES)
creds = flow.run_local_server(port=0)
print(json.dumps(json.loads(creds.to_json()), indent=2))
