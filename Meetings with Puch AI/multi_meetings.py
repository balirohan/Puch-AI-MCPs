import asyncio
import os
import datetime
from pathlib import Path
from typing import Annotated, Optional, List
from collections import defaultdict

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

ONBOARDING_URL = "http://127.0.0.1:8000" 

# Using the broader 'calendar' scope as it includes 'readonly' for free/busy checks.
SCOPES = ['https://www.googleapis.com/auth/calendar'] 
SERVICE_ACCOUNT_FILE = 'service_account.json'


# --- DATA MODELS ---

class RichToolDescription(BaseModel):
    description: str
    use_when: str
    side_effects: str | None

# --- AUTHENTICATION & SERVICE FACTORY ---

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

def get_calendar_service(impersonated_email: str = None):
    """
    Builds the Google Calendar service object. If an email is provided,
    it creates credentials that impersonate that user (requires domain-wide delegation).
    """
    try:
        base_creds = service_account.Credentials.from_service_account_file(
            SERVICE_ACCOUNT_FILE, scopes=SCOPES
        )
        creds = base_creds.with_subject(impersonated_email) if impersonated_email else base_creds
        
        service = build('calendar', 'v3', credentials=creds)
        return service
    except Exception as e:
        print(f"An error during service account authentication for '{impersonated_email}': {e}")
        return None

# --- MCP SERVER SETUP ---

mcp = FastMCP(
    "Google Calendar Smart Scheduler",
    auth=SimpleBearerAuthProvider(TOKEN),
)

# --- HELPER FUNCTIONS ---

def _get_onboarding_message(user_email: str):
    """Formats a user-friendly message with a link to the onboarding service."""
    return (
        f"I can't access that calendar. The user '{user_email}' may need to share their calendar with the service "
        f"or complete the onboarding at {ONBOARDING_URL}."
    )

def _format_available_slots(slots: list, duration_minutes: int) -> str:
    """Formats the list of available slots into a user-friendly message."""
    if not slots:
        return f"😔 I couldn't find any common free slots of {duration_minutes} minutes in the next 7 days during working hours."
    
    response_parts = [f"✅ Found some available slots for your {duration_minutes}-minute meeting. Here are the top 3:"]
    
    for slot_start in slots[:3]:
        slot_end = slot_start + datetime.timedelta(minutes=duration_minutes)
        formatted_str = (
            f"  - **{slot_start.strftime('%A, %b %d')}** at "
            f"**{slot_start.strftime('%I:%M %p')}** - {slot_end.strftime('%I:%M %p')}"
        )
        response_parts.append(formatted_str)
        
    response_parts.append("\nWhich one should I book?")
    return "\n".join(response_parts)

async def _fetch_all_events(user_emails: list[str], time_window_days: int) -> list[dict] | str:
    """Helper to fetch all events for conflict checking."""
    service = get_calendar_service() # Uses the main service account
    if not service:
        return "Could not connect to Google Calendar service."

    loop = asyncio.get_running_loop()
    all_events = []
    now = datetime.datetime.now(datetime.timezone.utc)
    time_max = now + datetime.timedelta(days=time_window_days)

    for email in user_emails:
        try:
            api_call = service.events().list(
                calendarId=email, timeMin=now.isoformat(), timeMax=time_max.isoformat(),
                singleEvents=True, orderBy='startTime'
            )
            events_result = await loop.run_in_executor(None, api_call.execute)
            for event in events_result.get('items', []):
                if 'dateTime' in event.get('start', {}) and 'dateTime' in event.get('end', {}):
                    event['owner'] = email
                    all_events.append(event)
        except HttpError as e:
            if e.resp.status == 404:
                return _get_onboarding_message(email)
            return f"An API error occurred for {email}: {e}"
    return all_events

def _format_conflicts(conflicts: list[tuple[dict, dict]]) -> str:
    """Takes a list of conflicting event pairs and formats them into a readable string."""
    if not conflicts:
        return "✅ No conflicts found in the calendars for the next 60 days."

    response_parts = [f"🚨 Found {len(conflicts)} potential conflict(s):"]

    for i, (event1, event2) in enumerate(conflicts):
        owner1, owner2 = event1.get('owner'), event2.get('owner')
        summary1, summary2 = event1.get('summary', 'Untitled'), event2.get('summary', 'Untitled')
        start1 = datetime.datetime.fromisoformat(event1['start']['dateTime']).strftime('%b %d, %I:%M %p')
        end1 = datetime.datetime.fromisoformat(event1['end']['dateTime']).strftime('%I:%M %p')
        start2 = datetime.datetime.fromisoformat(event2['start']['dateTime']).strftime('%b %d, %I:%M %p')
        end2 = datetime.datetime.fromisoformat(event2['end']['dateTime']).strftime('%I:%M %p')
        
        conflict_str = (
            f"\n--- Conflict {i+1} ---\n"
            f"  - **{owner1}** has **'{summary1}'** ({start1} - {end1})\n"
            f"  - **{owner2}** has **'{summary2}'** ({start2} - {end2})"
        )
        response_parts.append(conflict_str)
        
    return "\n".join(response_parts)

async def _find_events_by_query(user_email: str, query: str) -> list[dict] | str:
    """Helper to find a specific event by keyword search."""
    service = get_calendar_service()
    if not service:
        return "Error: Could not connect to Google Calendar service."

    now = datetime.datetime.now(datetime.timezone.utc)
    time_max = now + datetime.timedelta(days=60)
    
    try:
        loop = asyncio.get_running_loop()
        api_call = service.events().list(
            calendarId=user_email, q=query, timeMin=now.isoformat(),
            timeMax=time_max.isoformat(), singleEvents=True, orderBy='startTime'
        )
        events_result = await loop.run_in_executor(None, api_call.execute)
        return events_result.get('items', [])
    except HttpError as error:
        if error.resp.status == 404: return "NEEDS_ONBOARDING"
        return f"An API error occurred: {error}"

def _parse_recurrence_rule(frequency: str, days_of_week: Optional[List[str]] = None) -> str:
    """
    Translates natural language frequency into a Google Calendar RRULE string.
    """
    freq_map = {
        "daily": "DAILY",
        "weekly": "WEEKLY",
        "monthly": "MONTHLY",
        "yearly": "YEARLY",
    }
    rrule = f"RRULE:FREQ={freq_map.get(frequency.lower(), 'DAILY')}"

    if frequency.lower() == 'weekly' and days_of_week:
        valid_days = {"monday": "MO", "tuesday": "TU", "wednesday": "WE", "thursday": "TH", "friday": "FR", "saturday": "SA", "sunday": "SU"}
        day_codes = [valid_days[day.lower()] for day in days_of_week if day.lower() in valid_days]
        if day_codes:
            rrule += f";BYDAY={','.join(day_codes)}"
            
    return rrule

# --- MCP TOOLS ---

@mcp.tool(description=RichToolDescription(
    description="Finds a common available time slot for a meeting between multiple people in your organization for a specified duration.",
    use_when="A user wants to find a time to meet with colleagues, asking something like 'Find a 30-minute slot for me and Rohan next week'.",
    side_effects="None. This tool only reads free/busy calendar data and does not create any events."
).model_dump_json())
async def find_available_slot(
    attendees: Annotated[List[EmailStr], Field(description="A list of email addresses for all meeting attendees, including your own.")],
    duration_minutes: Annotated[int, Field(description="The desired duration of the meeting in minutes, e.g., 30 or 60.")]
) -> str:
    if len(attendees) < 2:
        return "Please provide at least two attendees to find a common slot."
    requester_email = attendees[0]
    service = get_calendar_service(impersonated_email=requester_email)
    if not service: return "Could not connect to Google Calendar. Please check server configuration and delegation settings."
    now = datetime.datetime.now(datetime.timezone.utc)
    freebusy_body = {
        "timeMin": now.isoformat(),
        "timeMax": (now + datetime.timedelta(days=7)).isoformat(),
        "items": [{"id": email} for email in attendees],
        "timeZone": "Asia/Kolkata"
    }
    try:
        loop = asyncio.get_running_loop()
        freebusy_result = await loop.run_in_executor(None, lambda: service.freebusy().query(body=freebusy_body).execute())
        all_busy_intervals = []
        for email in attendees:
            calendar_info = freebusy_result.get('calendars', {}).get(email, {})
            if calendar_info.get('errors'): return f"Could not check calendar for {email}."
            for busy_slot in calendar_info.get('busy', []):
                all_busy_intervals.append({"start": datetime.datetime.fromisoformat(busy_slot['start']), "end": datetime.datetime.fromisoformat(busy_slot['end'])})
        all_busy_intervals.sort(key=lambda x: x['start'])
        available_slots, search_start_time = [], (now.astimezone(datetime.timezone(datetime.timedelta(hours=5, minutes=30))) + datetime.timedelta(hours=1)).replace(minute=0, second=0, microsecond=0)
        for day_offset in range(7):
            day_start, work_day_end = search_start_time + datetime.timedelta(days=day_offset), (search_start_time + datetime.timedelta(days=day_offset)).replace(hour=18, minute=0)
            potential_slot_start = day_start.replace(hour=10, minute=0)
            for busy_interval in [bi for bi in all_busy_intervals if bi['start'].date() == potential_slot_start.date()]:
                if busy_interval['start'] - potential_slot_start >= datetime.timedelta(minutes=duration_minutes): available_slots.append(potential_slot_start)
                potential_slot_start = max(potential_slot_start, busy_interval['end'])
            if work_day_end - potential_slot_start >= datetime.timedelta(minutes=duration_minutes): available_slots.append(potential_slot_start)
            if len(available_slots) >= 5: break
        return _format_available_slots(available_slots, duration_minutes)
    except HttpError as e: return f"An error occurred with the Google API: {e}"
    except Exception as e:
        print(f"An unexpected error in find_available_slot: {e}")
        return "Sorry, I ran into an unexpected error."

@mcp.tool(description=RichToolDescription(
    description="Creates a recurring event or 'goal' in a user's calendar.",
    use_when="A user wants to set a recurring reminder or schedule a regular activity, like 'schedule gym time every morning' or 'remind me to read every weekday evening'.",
    side_effects="A new recurring event will be created in the user's primary calendar."
).model_dump_json())
async def create_recurring_goal(
    user_email: Annotated[EmailStr, Field(description="The email address of the user for whom to create the goal.")],
    title: Annotated[str, Field(description="The title of the goal or event, e.g., 'Gym', 'Learn Guitar'.")],
    duration_minutes: Annotated[int, Field(description="The duration of each session in minutes.")],
    frequency: Annotated[str, Field(description="How often the event should repeat. Supported values: 'daily', 'weekly'.")],
    time_of_day: Annotated[str, Field(description="When the event should occur. Supported values: 'morning', 'afternoon', 'evening'.")],
    days_of_week: Annotated[Optional[List[str]], Field(description="For weekly frequency, a list of days, e.g., ['Monday', 'Wednesday'].")] = None
) -> str:
    service = get_calendar_service()
    if not service: return "Error: Could not connect to Google Calendar service."
    time_map = {"morning": 7, "afternoon": 13, "evening": 18}
    start_hour = time_map.get(time_of_day.lower(), 9)
    today = datetime.date.today()
    start_time = datetime.datetime(today.year, today.month, today.day, start_hour, 0, 0, tzinfo=datetime.timezone(datetime.timedelta(hours=5, minutes=30)))
    end_time = start_time + datetime.timedelta(minutes=duration_minutes)
    rrule = _parse_recurrence_rule(frequency, days_of_week)
    event_body = {
        'summary': title,
        'start': {'dateTime': start_time.isoformat(), 'timeZone': 'Asia/Kolkata'},
        'end': {'dateTime': end_time.isoformat(), 'timeZone': 'Asia/Kolkata'},
        'recurrence': [rrule],
    }
    try:
        await asyncio.get_running_loop().run_in_executor(
            None, lambda: service.events().insert(calendarId=user_email, body=event_body).execute()
        )
        return f"✅ Done! I've scheduled '{title}' for you in your calendar."
    except HttpError as e:
        if e.resp.status == 404: return _get_onboarding_message(user_email)
        return f"Could not schedule goal. Reason: {e}"

@mcp.tool(description=RichToolDescription(
    description="Intelligently creates a new one-time event by first checking for conflicts among attendees.",
    use_when="When you want to schedule a simple, non-recurring event with other people.",
    side_effects="A new event will be added to the primary calendar of the user creating it, and invitations will be sent."
).model_dump_json())
async def create_calendar_event(
    user_email: Annotated[EmailStr, Field(description="The email of the user creating the event. This tool will act on their behalf.")],
    summary: Annotated[str, Field(description="The title or summary of the event.")],
    start_time: Annotated[str, Field(description="The proposed start time of the event in ISO 8601 format.")],
    end_time: Annotated[str, Field(description="The proposed end time of the event in ISO 8601 format.")],
    attendees: Annotated[Optional[List[EmailStr]], Field(description="A list of email addresses of people to invite.")] = None,
    location: Annotated[Optional[str], Field(description="The location of the event.")] = None,
    description: Annotated[Optional[str], Field(description="A description of the event.")] = None
) -> str:
    all_attendees = attendees if attendees else []
    if user_email not in all_attendees:
        all_attendees.append(user_email)

    service = get_calendar_service(impersonated_email=user_email)
    if not service: return "Error: Could not connect to Google Calendar service. Check delegation settings."
    
    freebusy_body = {
        "timeMin": start_time,
        "timeMax": end_time,
        "items": [{"id": email} for email in all_attendees]
    }
    try:
        loop = asyncio.get_running_loop()
        freebusy_result = await loop.run_in_executor(None, lambda: service.freebusy().query(body=freebusy_body).execute())
        
        conflicting_attendees = []
        for email, data in freebusy_result.get('calendars', {}).items():
            if data.get('busy'):
                conflicting_attendees.append(email)
        
        if conflicting_attendees:
            return f"⚠️ **Conflict!** The proposed time slot is busy for: {', '.join(conflicting_attendees)}. Please try finding an available slot first."

        event = {
            'summary': summary, 'location': location, 'description': description,
            'start': {'dateTime': start_time, 'timeZone': 'Asia/Kolkata'},
            'end': {'dateTime': end_time, 'timeZone': 'Asia/Kolkata'},
            'attendees': [{'email': email} for email in all_attendees],
        }
        main_service = get_calendar_service()
        created_event = await loop.run_in_executor(
            None, lambda: main_service.events().insert(calendarId=user_email, body=event, sendUpdates="all").execute()
        )
        return f"✅ No conflicts found. Event '{summary}' has been scheduled and invitations sent."

    except HttpError as e:
        if e.resp.status == 404: return _get_onboarding_message(user_email)
        return f"Could not schedule event. Reason: {e}"
    except Exception as e:
        print(f"An unexpected error in create_calendar_event: {e}")
        return "Sorry, I ran into an unexpected error."
        
@mcp.tool(description=RichToolDescription(
    description="Finds and reports scheduling conflicts among a list of users.",
    use_when="A user wants to find a common free time or check for conflicts between a group of people.",
    side_effects="None. This tool only reads calendar data."
).model_dump_json())
async def find_calendar_conflicts(
    user_emails: Annotated[list[EmailStr], Field(description="A list of the email addresses of the users whose calendars should be checked.")],
) -> str:
    if len(user_emails) < 2: return "Please provide at least two email addresses to check for conflicts."
    all_events = await _fetch_all_events(user_emails, time_window_days=60)
    if isinstance(all_events, str): return all_events
    all_events.sort(key=lambda e: e['start']['dateTime'])
    conflicts, reported_pairs = [], set()
    for i in range(len(all_events)):
        for j in range(i + 1, len(all_events)):
            event1, event2 = all_events[i], all_events[j]
            if event1['owner'] == event2['owner']: continue
            start1, end1 = datetime.datetime.fromisoformat(event1['start']['dateTime']), datetime.datetime.fromisoformat(event1['end']['dateTime'])
            start2, end2 = datetime.datetime.fromisoformat(event2['start']['dateTime']), datetime.datetime.fromisoformat(event2['end']['dateTime'])
            if start1 < end2 and start2 < end1:
                pair_id = tuple(sorted((event1['id'], event2['id'])))
                if pair_id not in reported_pairs:
                    conflicts.append((event1, event2))
                    reported_pairs.add(pair_id)
    return _format_conflicts(conflicts)

# --- RESTORED TOOLS ---

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
    if not service: return "Error: Could not connect to Google Calendar service."
    now = datetime.datetime.now(datetime.timezone.utc).isoformat()
    try:
        api_call = service.events().list(calendarId=user_email, timeMin=now, maxResults=max_results, singleEvents=True, orderBy='startTime')
        events_result = await asyncio.get_running_loop().run_in_executor(None, api_call.execute)
        events = events_result.get('items', [])
        if not events: return f"No upcoming events found for {user_email}."
        event_list = f"Upcoming Events for {user_email}:\n"
        for event in events:
            start = event.get('start',{}).get('dateTime', event.get('start',{}).get('date'))
            event_list += f"\n- Summary: {event.get('summary', 'No Title')}\n  Time: {start}\n"
        return event_list
    except HttpError as error:
        if error.resp.status == 404: return _get_onboarding_message(user_email)
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
        if not service: return "Error: Could not connect to Google Calendar service."
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
        if not service: return "Error: Could not connect to Google Calendar service."
        await asyncio.get_running_loop().run_in_executor(
            None, lambda: service.events().delete(calendarId=user_email, eventId=event_to_delete['id']).execute()
        )
        return f"Successfully deleted the event '{event_to_delete.get('summary')}' for {user_email}."
    except HttpError as error:
        if error.resp.status == 404: return _get_onboarding_message(user_email)
        return f"An error occurred while deleting the event for {user_email}: {error}"


# --- Standard Validation Tool ---
@mcp.tool
async def validate() -> str:
    """NOTE: This tool must be present in an MCP server used by Puch for validation."""
    return MY_NUMBER

# --- MAIN EXECUTION BLOCK ---

async def main():
    """The main coroutine that starts the MCP server."""
    print("Starting Google Calendar Smart Scheduler on http://0.0.0.0:8085")
    await mcp.run_async("streamable-http", host="0.0.0.0", port=8085)

if __name__ == "__main__":
    try:
        asyncio.run(main())
    except (KeyboardInterrupt, SystemExit):
        print("Server shutting down.")
