# Google Calendar NLP Assistant via Puch AI

This project provides a self-hosted MCP (Model Context Protocol) server that connects your Google Calendar to Puch AI. It allows you to manage your calendar—creating, reading, updating, and deleting events—using natural language commands sent from WhatsApp.

### What is MCP?

**Model Context Protocol (MCP)** is a standardized method for managing and delivering contextual information to AI models. It structures and organizes elements such as system instructions, user preferences, memory, and conversation history to ensure consistent and personalized model behavior across interactions. By using MCP, developers can maintain richer, more relevant, and adaptive conversations with AI systems.

## Features
- **Create Events:** "Schedule a meeting for tomorrow at 3 PM titled 'Project Brainstorm'."
- **Read Events:** "What's on my schedule for this Friday?"
- **Update Events:** "Reschedule my 'Project Brainstorm' to 4 PM." _(Note: Requires event ID)_
- **Delete Events:** "Cancel my 'Dentist Appointment' next week." _(Note: Requires event ID)_
- **Natural Language:** All interactions are handled through conversational commands.
- **Secure & Private:** Your credentials stay on your local machine and are not exposed.

---

## Setup and Installation Guide

Follow these steps carefully to get your server running.

### Step 1: Clone the Repository

First, get the project code onto your local machine.

```
git clone https://github.com/balirohan/Puch-AI-MCPs.git
cd Meetings\ with\ Puch\ AI/
```

### Step 2: Set Up the Python Environment

It's crucial to use a virtual environment to manage dependencies and avoid conflicts.

1. Create a virtual environment:

  ```
  python -m venv .venv
  ```

2. Activate the virtual environment:

  - On macOS and Linux:

    ```
    source .venv/bin/activate
    ```

  - On Windows

    ```
    .\.venv\Scripts\activate
    ```

3. Install the required libraries:
   
   The requirements.txt file contains all the necessary Python packages.

   ```
   pip install -r requirements.txt
   ```

### ✅ Step 3: Configure Google Cloud & Service Account (Web App)

To allow your web application to access Google Calendar **programmatically** using a **Service Account**, follow these steps:

---

#### 1. Create a Project

- Go to the [Google Cloud Console](https://console.cloud.google.com/).
- Create a **new project** or select an **existing one**.

---

#### 2. Enable the Google Calendar API

- Navigate to `APIs & Services > Library`.
- Search for **Google Calendar API**.
- Click **Enable**.

---

#### 3. Create a Service Account

- Go to `IAM & Admin > Service Accounts`.
- Click **+ CREATE SERVICE ACCOUNT**.
- Enter a name like `calendar-access-bot`.
- Click **Create and Continue**.
- (Optional) Assign roles if needed (you can skip this).
- Click **Done**.

---

#### 4. Generate and Download the Service Account Key

- Find the newly created service account in the list.
- Click on the **three dots** (⋮) > **Manage keys**.
- Click **Add Key > Create new key**.
- Choose **JSON** format.
- Click **Create** – the file will download automatically.
- Rename the file to `service_account.json` and move it to your project's root directory.

---

✅ Your service account now has access to the calendar and can be used by your app to read/write events.


### Step 4: Configure Local Environment Variables

You need to provide the secrets for your MCP server.

1. Create a '.env' file in the root of your project directory.

2. Add the following content to the .env file, replacing the placeholder values with your actual Puch AI credentials:

   ```
   PUCH_TOKEN="your_secret_puch_token_here"
   MY_PHONE_NUMBER="your_phone_number_for_validation" (e.g. "9188xxxxxxxx")
   SERVICE_ACCOUNT_EMAIL=<your_service_account_email>
   ```

### Step 5: First-Time Authentication

The very first time you run the server, you must grant it access to your Google Calendar.

1. **Run the application:**

   ```
   python multi_meetings.py
   python onboarding.py
   ```

2. Open your web browser and go to the following address: ```http://127.0.0.1:8000```

3. Log in with the same Google account you added as a "Test user". (this step is required for an app in testing, but not for an app in production)

4. You will see a screen asking for permission to "View and edit events on all your calendars". Click **Allow**.

5. After you grant permission you will be able to manage your Google Calendar using Puch AI from WhatsApp.


### Step 6: Connect to Puch AI

Now your server is fully configured and ready for use.

1. Expose your local server to the internet:

  The server is running on your local machine, but Puch AI needs a public URL to reach it. Use a tool like ngrok for this. 

  ```
  ngrok http 8085
  ```

3. ngrok will provide you with a public URL (e.g., https://random-string.ngrok.io). Copy this HTTPS URL.

4. Provide the URL to Puch AI:

  - Chat with Puch AI using the following link - https://s.puch.ai/puchai
  - Connect Puch AI to your MCP server using the following command:

    ```
    /mcp connect <your-public-ngrok-link>/mcp <your_puch_secret_token>
    ```

### Step 7: Interact with Your Calendar via WhatsApp

You're all set! You can now send natural language commands to your Puch AI contact on WhatsApp.

Example Commands:

"Schedule a dentist appointment for next Tuesday at 10 AM for 45 minutes."

"What's on my calendar tomorrow?"

"Create an event: 'Team Lunch' at 1 PM on Friday."


### Screenshots

**Puch AI**
![IMG_3604](https://github.com/user-attachments/assets/21b582c1-346b-4d72-82ba-4a5548c4fdde)

**User Authorization**
![IMG_3605](https://github.com/user-attachments/assets/0a131c0d-e326-4022-bbd4-3caf0b439a38)
![IMG_3606](https://github.com/user-attachments/assets/e885d4b4-bb57-4abe-8118-70ea8d426095)
![IMG_3607](https://github.com/user-attachments/assets/68759fda-e07b-4e25-8de3-f88c50b0e355)




