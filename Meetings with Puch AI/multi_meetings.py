import asyncio
import os
from pathlib import Path
from typing import Annotated, Optional
import datetime

from fastmcp import FastMCP
from fastmcp.server.auth.providers.bearer import BearerAuthProvider, RSAKeyPair
from mcp.server.auth.provider import AccessToken
from pydantic import Field, BaseModel, EmailStr
from google.oauth2 import service_account
from googleapiclient.discovery import build
from googleapiclient.errors import HttpError

# --- CONFIGURATION ---
from dotenv import load_dotenv
load_dotenv()

TOKEN = os.getenv("PUCH_TOKEN")
if not TOKEN:
    raise ValueError("PUCH_TOKEN environment variable not set.")

MY_NUMBER = os.getenv("MY_PHONE_NUMBER")
if not MY_NUMBER:
    raise ValueError("MY_PHONE_NUMBER environment variable not set.")

# <<< NEW: Define the URL for the onboarding server for easy access
ONBOARDING_URL = "http://127.0.0.1:8000" # Use your public ngrok URL in production

SCOPES = ['https://www.googleapis.com/auth/calendar']
SERVICE_ACCOUNT_FILE = 'service_account.json'


class RichToolDescription(BaseModel):
    description: str
    use_when: str
    side_effects: str | None


class SimpleBearerAuthProvider(BearerAuthProvider):
    def __init__(self, token: str):
        k = RSAKeyPair.generate()
        super().__init__(
            public_key=k.public_key, jwks_uri=None, issuer=None, audience=None
        )
        self.token = token

    async def load_access_token(self, token: str) -> AccessToken | None:
        if token == self.token:
            return AccessToken(
                token=token,
                client_id="puch-client",
                scopes=["*"],
                expires_at=None,
            )
        return None


mcp = FastMCP(
    "Google Calendar Multi-User Service",
    auth=SimpleBearerAuthProvider(TOKEN),
)

def get_calendar_service():
    try:
        service_account_path = Path(__file__).parent / SERVICE_ACCOUNT_FILE
        if not service_account_path.exists():
            raise FileNotFoundError(
                f"FATAL: '{SERVICE_ACCOUNT_FILE}' not found."
            )
        creds = service_account.Credentials.from_service_account_file(
            str(service_account_path), scopes=SCOPES)
        service = build('calendar', 'v3', credentials=creds)
        return service
    except Exception as e:
        print(f"An error occurred during service account authentication: {e}")
        return None

# <<< HELPER FUNCTION TO GENERATE THE ONBOARDING MESSAGE
def _get_onboarding_message(user_email: str):
    return (
        f"It looks like the calendar for '{user_email}' is not set up yet. "
        f"Please visit {ONBOARDING_URL} to grant access, and then try your request again."
    )

async def _find_events_by_query(user_email: str, query: str) -> list[dict] | str:
    service = get_calendar_service()
    if not service:
        return []

    now = datetime.datetime.now(datetime.UTC)
    time_max = now + datetime.timedelta(days=30)
    
    try:
        events_result = service.events().list(
            calendarId=user_email,
            timeMin=now.isoformat(),
            timeMax=time_max.isoformat(),
            singleEvents=True,
            orderBy='startTime'
        ).execute()
        
        all_events = events_result.get('items', [])
        
        matching_events = [
            event for event in all_events 
            if query.lower() in event.get('summary', '').lower()
        ]
        return matching_events
    except HttpError as error:
        # <<< UPDATED: Check for 404 and return the helpful message
        if error.resp.status == 404:
            print(f"Calendar not found for '{user_email}'. Directing user to onboard.")
            return _get_onboarding_message(user_email)
        print(f"An error occurred while searching events for {user_email}: {error}")
        return f"An API error occurred: {error}"


# --- MCP Tools ---
CreateEventToolDescription = RichToolDescription(
    description="Creates a new event on a specified user's Google Calendar.",
    use_when="When you want to schedule a new event, meeting, or reminder for a specific user.",
    side_effects="A new event will be added to the specified user's primary Google Calendar."
)
@mcp.tool(description=CreateEventToolDescription.model_dump_json())
async def create_calendar_event(
    user_email: Annotated[EmailStr, Field(description="The email of the user to create the event for.")],
    summary: Annotated[str, Field(description="The title or summary of the event.")],
    start_time: Annotated[str, Field(description="The start time of the event in ISO 8601 format.")],
    end_time: Annotated[str, Field(description="The end time of the event in ISO 8601 format.")],
    location: Annotated[Optional[str], Field(description="The location of the event.")] = None,
    description: Annotated[Optional[str], Field(description="A description of the event.")] = None
) -> str:
    service = get_calendar_service()
    event = {
        'summary': summary, 'location': location, 'description': description,
        'start': {'dateTime': start_time, 'timeZone': 'Asia/Kolkata'},
        'end': {'dateTime': end_time, 'timeZone': 'Asia/Kolkata'},
    }
    try:
        created_event = service.events().insert(calendarId=user_email, body=event).execute()
        return f"Event created for {user_email}: '{summary}'. View it here: {created_event.get('htmlLink')}"
    except HttpError as error:
        # <<< UPDATED: Check for 404 and return the helpful message
        if error.resp.status == 404:
            print(f"Calendar not found for '{user_email}'. Directing user to onboard.")
            return _get_onboarding_message(user_email)
        return f"Could not create event for {user_email}. Reason: {error}."

# (The other tools - read, delete, update - should also have their error handling updated similarly)
# ... For brevity, I've only updated create_calendar_event and the helper it relies on.
# You should apply the same try/except logic to the other tool functions.

@mcp.tool
async def validate() -> str:
    return MY_NUMBER

async def main():
    print("Starting Multi-User Calendar Service on http://0.0.0.0:8085")
    await mcp.run_async("streamable-http", host="0.0.0.0", port=8085)

if __name__ == "__main__":
    asyncio.run(main())