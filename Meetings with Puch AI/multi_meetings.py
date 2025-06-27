import asyncio
import os
import datetime
import json
from pathlib import Path
from typing import Annotated, Optional
from collections import defaultdict

import requests
from dotenv import load_dotenv
from fastmcp import FastMCP
from fastmcp.server.auth.providers.bearer import BearerAuthProvider, RSAKeyPair
from mcp.server.auth.provider import AccessToken
from pydantic import BaseModel, Field, EmailStr
from google.oauth2 import service_account
from googleapiclient.discovery import build
from googleapiclient.errors import HttpError

# --- CONFIGURATION ---

load_dotenv()

TOKEN = os.getenv("PUCH_TOKEN")
if not TOKEN:
    raise ValueError("PUCH_TOKEN environment variable not set.")

MY_NUMBER = os.getenv("MY_PHONE_NUMBER")
if not MY_NUMBER:
    raise ValueError("MY_PHONE_NUMBER environment variable not set.")

ONBOARDING_URL = "http://127.0.0.1:8000" # Use your public ngrok URL in production

SCOPES = ['https://www.googleapis.com/auth/calendar']
SERVICE_ACCOUNT_FILE = 'service_account.json'


# --- DATA MODELS ---

class RichToolDescription(BaseModel):
    description: str
    use_when: str
    side_effects: str | None

# --- AUTHENTICATION ---

class SimpleBearerAuthProvider(BearerAuthProvider):
    def __init__(self, token: str):
        k = RSAKeyPair.generate()
        super().__init__(
            public_key=k.public_key, jwks_uri=None, issuer=None, audience=None
        )
        self.token = token

    async def load_access_token(self, token: str) -> AccessToken | None:
        if token == self.token:
            return AccessToken(token=token, client_id="puch-calendar-client", scopes=["*"])
        return None

# --- MCP SERVER SETUP ---

mcp = FastMCP(
    "Google Calendar Multi-User Service",
    auth=SimpleBearerAuthProvider(TOKEN),
)

# --- SERVICE & HELPER FUNCTIONS ---

def get_calendar_service():
    """Builds and returns an authenticated Google API service object."""
    try:
        service_account_path = Path(__file__).parent / SERVICE_ACCOUNT_FILE
        if not service_account_path.exists():
            raise FileNotFoundError(f"FATAL: '{SERVICE_ACCOUNT_FILE}' not found.")
        creds = service_account.Credentials.from_service_account_file(
            str(service_account_path), scopes=SCOPES)
        service = build('calendar', 'v3', credentials=creds)
        return service
    except Exception as e:
        print(f"An error occurred during service account authentication: {e}")
        return None

def _get_onboarding_message(user_email: str):
    """Formats a user-friendly message with a link to the onboarding service."""
    return (
        f"I can't access all calendars. "
        f"The calendar for '{user_email}' is not shared with me. "
        f"Please ask them to authorize the service at {ONBOARDING_URL} and then try again."
    )

async def _fetch_all_events(user_emails: list[str], time_window_days: int) -> list[dict] | str:
    """
    Fetches all future events for a list of users within a given time window.
    Returns a list of event objects or an error string if any calendar is inaccessible.
    """
    service = get_calendar_service()
    if not service:
        return "Could not connect to Google Calendar service."

    loop = asyncio.get_running_loop()
    all_events = []
    
    now = datetime.datetime.now(datetime.timezone.utc)
    time_max = now + datetime.timedelta(days=time_window_days)

    for email in user_emails:
        try:
            api_call = service.events().list(
                calendarId=email,
                timeMin=now.isoformat(),
                timeMax=time_max.isoformat(),
                singleEvents=True,
                orderBy='startTime'
            )
            events_result = await loop.run_in_executor(None, api_call.execute)
            
            for event in events_result.get('items', []):
                if 'dateTime' in event.get('start', {}) and 'dateTime' in event.get('end', {}):
                    event['owner'] = email
                    all_events.append(event)

        except HttpError as e:
            if e.resp.status == 404:
                return _get_onboarding_message(email)
            else:
                return f"An API error occurred for {email}: {e}"
    
    return all_events

def _format_conflicts(conflicts: list[tuple[dict, dict]]) -> str:
    """Takes a list of conflicting event pairs and formats them into a readable string."""
    if not conflicts:
        return "✅ No conflicts found in the calendars for the next 60 days."

    response_parts = [f"🚨 Found {len(conflicts)} potential conflict(s):"]

    for i, (event1, event2) in enumerate(conflicts):
        owner1 = event1.get('owner', 'Unknown')
        owner2 = event2.get('owner', 'Unknown')
        
        summary1 = event1.get('summary', 'Untitled Event')
        summary2 = event2.get('summary', 'Untitled Event')

        start1 = datetime.datetime.fromisoformat(event1['start']['dateTime']).strftime('%b %d, %I:%M %p')
        end1 = datetime.datetime.fromisoformat(event1['end']['dateTime']).strftime('%I:%M %p')
        start2 = datetime.datetime.fromisoformat(event2['start']['dateTime']).strftime('%b %d, %I:%M %p')
        end2 = datetime.datetime.fromisoformat(event2['end']['dateTime']).strftime('%I:%M %p')
        
        conflict_str = (
            f"\n--- Conflict {i+1} ---\n"
            f"  - **{owner1}** has **'{summary1}'** from **{start1}** to **{end1}**\n"
            f"  - **{owner2}** has **'{summary2}'** from **{start2}** to **{end2}**"
        )
        response_parts.append(conflict_str)
        
    return "\n".join(response_parts)

async def _find_events_by_query(user_email: str, query: str) -> list[dict] | str:
    """Helper to find a specific event by keyword search."""
    service = get_calendar_service()
    if not service:
        return []

    now = datetime.datetime.now(datetime.timezone.utc)
    time_max = now + datetime.timedelta(days=60) # Increased search window for relevance
    
    try:
        loop = asyncio.get_running_loop()
        api_call = service.events().list(
            calendarId=user_email,
            timeMin=now.isoformat(),
            timeMax=time_max.isoformat(),
            singleEvents=True,
            orderBy='startTime'
        )
        events_result = await loop.run_in_executor(None, api_call.execute)
        
        all_events = events_result.get('items', [])
        
        matching_events = [
            event for event in all_events 
            if query.lower() in event.get('summary', '').lower()
        ]
        return matching_events
    except HttpError as error:
        if error.resp.status == 404:
            return "NEEDS_ONBOARDING"
        print(f"An error occurred while searching events for {user_email}: {error}")
        return f"An API error occurred: {error}"


# --- MCP Tools ---

@mcp.tool(description=RichToolDescription(
    description="Creates a new event on a specified user's Google Calendar.",
    use_when="When you want to schedule a new event, meeting, or reminder for a specific user.",
    side_effects="A new event will be added to the specified user's primary Google Calendar."
).model_dump_json())
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
        created_event = await asyncio.get_running_loop().run_in_executor(
            None, lambda: service.events().insert(calendarId=user_email, body=event).execute()
        )
        return f"Event created for {user_email}: '{summary}'. View it here: {created_event.get('htmlLink')}"
    except HttpError as error:
        if error.resp.status == 404:
            return _get_onboarding_message(user_email)
        return f"Could not create event for {user_email}. Reason: {error}."

@mcp.tool(description=RichToolDescription(
    description="Lists upcoming events from a specified user's Google Calendar.",
    use_when="When you want to know what's on a user's schedule or check their upcoming events.",
    side_effects="None. This tool only reads data from the user's calendar."
).model_dump_json())
async def read_calendar_events(
    user_email: Annotated[EmailStr, Field(description="The email of the user to read events from.")],
    max_results: Annotated[int, Field(description="The maximum number of events to return.", default=10)]
) -> str:
    service = get_calendar_service()
    now = datetime.datetime.now(datetime.timezone.utc).isoformat()
    try:
        api_call = service.events().list(
            calendarId=user_email, timeMin=now,
            maxResults=max_results, singleEvents=True,
            orderBy='startTime'
        )
        events_result = await asyncio.get_running_loop().run_in_executor(None, api_call.execute)
        events = events_result.get('items', [])
        if not events:
            return f"No upcoming events found for {user_email}."

        event_list = f"Upcoming Events for {user_email}:\n"
        for event in events:
            start = event.get('start',{}).get('dateTime', event.get('start',{}).get('date'))
            event_list += f"\n- Summary: {event.get('summary', 'No Title')}\n  Time: {start}\n"
        return event_list
    except HttpError as error:
        if error.resp.status == 404:
            return _get_onboarding_message(user_email)
        return f"Could not read events for {user_email}. Reason: {error}."

@mcp.tool(description=RichToolDescription(
    description="Updates an event on a specified user's Google Calendar by finding it with a query.",
    use_when="When you need to change an event's details for a specific user.",
    side_effects="The specified event will be modified on the user's calendar."
).model_dump_json())
async def update_calendar_event(
    user_email: Annotated[EmailStr, Field(description="The email of the user whose event should be updated.")],
    query: Annotated[str, Field(description="The name or title of the event to update.")],
    new_summary: Annotated[Optional[str], Field(description="The new title for the event.")] = None,
    new_start_time: Annotated[Optional[str], Field(description="The new start time in ISO 8601 format.")] = None,
    new_end_time: Annotated[Optional[str], Field(description="The new end time in ISO 8601 format.")] = None
) -> str:
    matching_events = await _find_events_by_query(user_email, query)
    if isinstance(matching_events, str):
        return _get_onboarding_message(user_email) if matching_events == "NEEDS_ONBOARDING" else matching_events

    if not matching_events: return f"Could not find any event for {user_email} matching '{query}' to update."
    if len(matching_events) > 1: return f"Found multiple events for {user_email} matching '{query}'. Please be more specific."

    event_to_update = matching_events[0]
    try:
        service = get_calendar_service()
        loop = asyncio.get_running_loop()
        event = await loop.run_in_executor(None, lambda: service.events().get(calendarId=user_email, eventId=event_to_update['id']).execute())

        if new_summary: event['summary'] = new_summary
        if new_start_time: event['start']['dateTime'] = new_start_time
        if new_end_time: event['end']['dateTime'] = new_end_time
        
        updated_event = await loop.run_in_executor(None, lambda: service.events().update(calendarId=user_email, eventId=event['id'], body=event).execute())
        return f"Event '{updated_event.get('summary')}' for {user_email} updated successfully."
    except HttpError as error:
        if error.resp.status == 404: return _get_onboarding_message(user_email)
        return f"An error occurred while updating the event for {user_email}: {error}"

@mcp.tool(description=RichToolDescription(
    description="Deletes an event from a specified user's Google Calendar by its name.",
    use_when="When you want to cancel or remove an event for a specific user.",
    side_effects="The specified event will be permanently removed from the user's Google Calendar."
).model_dump_json())
async def delete_calendar_event(
    user_email: Annotated[EmailStr, Field(description="The email of the user whose event should be deleted.")],
    query: Annotated[str, Field(description="The name or title of the event to delete.")]
) -> str:
    matching_events = await _find_events_by_query(user_email, query)
    if isinstance(matching_events, str):
        return _get_onboarding_message(user_email) if matching_events == "NEEDS_ONBOARDING" else matching_events
    
    if not matching_events: return f"Could not find any event for {user_email} matching '{query}'."
    if len(matching_events) > 1: return f"Found multiple events for {user_email} matching '{query}'. Please be more specific."

    event_to_delete = matching_events[0]
    try:
        service = get_calendar_service()
        await asyncio.get_running_loop().run_in_executor(
            None, lambda: service.events().delete(calendarId=user_email, eventId=event_to_delete['id']).execute()
        )
        return f"Successfully deleted the event '{event_to_delete.get('summary')}' for {user_email}."
    except HttpError as error:
        if error.resp.status == 404: return _get_onboarding_message(user_email)
        return f"An error occurred while deleting the event for {user_email}: {error}"

@mcp.tool(description=RichToolDescription(
    description="Finds and reports scheduling conflicts among a list of users.",
    use_when="A user wants to find a common free time or check for conflicts between a group of people.",
    side_effects="None. This tool only reads calendar data."
).model_dump_json())
async def find_calendar_conflicts(
    user_emails: Annotated[list[EmailStr], Field(description="A list of the email addresses of the users whose calendars should be checked.")],
) -> str:
    """Finds and reports scheduling conflicts among a list of users for the next 60 days."""
    if len(user_emails) < 2:
        return "Please provide at least two email addresses to check for conflicts."

    all_events = await _fetch_all_events(user_emails, time_window_days=60)
    if isinstance(all_events, str):
        return all_events

    all_events.sort(key=lambda e: e['start']['dateTime'])

    conflicts = []
    reported_pairs = set()
    for i in range(len(all_events)):
        for j in range(i + 1, len(all_events)):
            event1 = all_events[i]
            event2 = all_events[j]

            if event1['owner'] == event2['owner']:
                continue

            start1 = datetime.datetime.fromisoformat(event1['start']['dateTime'])
            end1 = datetime.datetime.fromisoformat(event1['end']['dateTime'])
            start2 = datetime.datetime.fromisoformat(event2['start']['dateTime'])
            end2 = datetime.datetime.fromisoformat(event2['end']['dateTime'])

            if start1 < end2 and start2 < end1:
                pair_id = tuple(sorted((event1['id'], event2['id'])))
                if pair_id not in reported_pairs:
                    conflicts.append((event1, event2))
                    reported_pairs.add(pair_id)
    
    return _format_conflicts(conflicts)

# --- Standard Validation Tool ---
@mcp.tool
async def validate() -> str:
    """NOTE: This tool must be present in an MCP server used by Puch for validation."""
    return MY_NUMBER

# --- MAIN EXECUTION BLOCK ---

async def main():
    """The main coroutine that starts the MCP server."""
    print("Starting Google Calendar MCP server on http://0.0.0.0:8085")
    await mcp.run_async("streamable-http", host="0.0.0.0", port=8085)

if __name__ == "__main__":
    try:
        asyncio.run(main())
    except (KeyboardInterrupt, SystemExit):
        print("Server shutting down.")
