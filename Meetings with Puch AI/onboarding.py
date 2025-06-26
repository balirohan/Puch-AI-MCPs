import os
import uvicorn
from fastapi import FastAPI, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from google_auth_oauthlib.flow import Flow
from googleapiclient.discovery import build
from googleapiclient.errors import HttpError
from dotenv import load_dotenv
from starlette.middleware.sessions import SessionMiddleware

# This line tells the oauthlib library to allow http connections for local testing.
os.environ['OAUTHLIB_INSECURE_TRANSPORT'] = '1'

# --- CONFIGURATION ---
load_dotenv()

SERVICE_ACCOUNT_EMAIL = os.getenv("SERVICE_ACCOUNT_EMAIL")
if not SERVICE_ACCOUNT_EMAIL:
    raise ValueError("SERVICE_ACCOUNT_EMAIL not set in .env file.")

CLIENT_SECRETS_FILE = 'web_credentials.json'
SCOPES = ['https://www.googleapis.com/auth/calendar.acls']
REDIRECT_URI = 'http://127.0.0.1:8000/oauth2callback'

app = FastAPI()
app.add_middleware(SessionMiddleware, secret_key=os.urandom(24))


# --- WEB APPLICATION ENDPOINTS ---

@app.get("/", response_class=HTMLResponse)
async def root():
    return """
    <html><head><title>Authorize Calendar Access</title></head>
    <body><h1>Grant Calendar Access</h1>
    <p>Click the button below to allow our service to manage your calendar.</p>
    <button onclick="window.location.href='/authorize'">Authorize with Google</button>
    </body></html>
    """

@app.get("/authorize")
async def authorize(request: Request):
    flow = Flow.from_client_secrets_file(
        CLIENT_SECRETS_FILE, scopes=SCOPES, redirect_uri=REDIRECT_URI
    )
    authorization_url, state = flow.authorization_url(
        access_type='offline', include_granted_scopes='true'
    )
    request.session['state'] = state
    return RedirectResponse(authorization_url)


@app.get("/oauth2callback")
async def oauth2callback(request: Request):
    state = request.session['state']
    flow = Flow.from_client_secrets_file(
        CLIENT_SECRETS_FILE, scopes=SCOPES, state=state, redirect_uri=REDIRECT_URI
    )
    flow.fetch_token(authorization_response=str(request.url))
    user_credentials = flow.credentials

    try:
        service = build('calendar', 'v3', credentials=user_credentials)
        rule = {'scope': {'type': 'user', 'value': SERVICE_ACCOUNT_EMAIL}, 'role': 'writer'}
        created_rule = service.acl().insert(calendarId='primary', body=rule).execute()
        
        print(f"Successfully shared calendar with {SERVICE_ACCOUNT_EMAIL}")
        
        return HTMLResponse("""
        <html><head><title>Success!</title></head>
        <body><h1>Authorization Successful!</h1>
        <p>Your calendar has been successfully shared with our service.</p>
        <p>You can now close this window and use the Puch AI service.</p>
        </body></html>
        """)
    except HttpError as error:
        print(f"An error occurred: {error}")
        return HTMLResponse(f"An error occurred: {error}", status_code=500)


if __name__ == "__main__":
    print("Starting onboarding server on http://127.0.0.1:8000")
    uvicorn.run(app, host="127.0.0.1", port=8000)