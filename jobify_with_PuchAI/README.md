# Puch AI Job Application Assistant

This project sets up a custom MCP server that extends Puch AI's capabilities for job applications. With this server, Puch AI can:

1.  **Read Your Resume:** Automatically extract text from your resume PDF.

2.  **Evaluate Job Fit:** Analyze your resume against a job description, identify strengths and weaknesses, and provide a compatibility score out of 10.

3.  **Conditionally Generate Cover Letters:** If your compatibility score is above 7.5, Puch AI will automatically draft a personalized cover letter for the specified company.

All these steps can be triggered with a single prompt after accessing your MCP server via Puch AI in WhatsApp!

## Prerequisites

Before you begin, ensure you have the following:

* **Python 3.8+** installed on your system.

* **`pip`** (Python package installer) installed.

* **A WhatsApp account** linked to the phone number you will register.

* **Your resume in PDF format** named `my_resume.pdf`.

* **`ngrok`** installed and set up (or another tool to expose your local server to the internet). You can download `ngrok` from [ngrok.com](https://ngrok.com/).

## Getting Started

Follow these steps to set up and run your custom MCP server:

### Step 1: Connect with Puch AI

1.  Open your web browser and navigate to the Puch AI WhatsApp invitation link: <https://s.puch.ai/puchai>.

2.  Follow the prompts to connect Puch AI to your WhatsApp.

### Step 2: Obtain Your Unique Token

1.  Once connected, send a message to Puch AI in WhatsApp:

    ```
    /apply <link_to_x_or_linkedin_post>
    ```

    Replace `<link_to_x_or_linkedin_post>` with a link to any public X (formerly Twitter) or LinkedIn post. Puch AI uses this to generate a unique token for your MCP server.

2.  Puch AI will reply with your unique token. **Keep this token safe!**

### Step 3: Prepare Your Project Files

1.  **Clone this repository** (or download the files) to your local machine.

2.  Ensure you have the following files in your project directory:

    * `requirements.txt`

    * `job_evaluator.py` (or whatever you named your main Python script containing the MCP server code)

3.  **Place your resume:** Rename your resume PDF to `my_resume.pdf` and place it in the same directory as `job_evaluator.py`.

### Step 4: Set Up Environment Variables (`.env` file)

To keep your sensitive information secure and out of your public code, we use environment variables.

1.  In the same directory as your `job_evaluator.py` script, create a new file named `.env` (note the leading dot).

2.  Open the `.env` file and add the following lines, replacing the placeholder values with your actual token and WhatsApp-registered phone number:

    ```
    PUCH_TOKEN="YOUR_UNIQUE_TOKEN_FROM_PUCH"
    MY_PHONE_NUMBER="YOUR_WHATSAPP_PHONE_NUMBER_WITHOUT_PLUS_SIGN_E.G._9188xxxxxxxx"
    ```

    **Important:** Never commit your `.env` file to version control (e.g., GitHub)! Add `.env` to your `.gitignore` file.

### Step 5: Create and activate virtual environment

What is a virtual environment, you might ask? Well, A virtual environment in Python is an isolated workspace that allows you to manage project-specific dependencies without affecting the global Python installation.

**🔒 Why it's useful:**

- Keeps dependencies separate between projects

- Prevents version conflicts

- Makes projects more portable and easier to deploy

You create one using:

```
python -m venv .venv
```

Then activate it:

```
source venv/bin/activate  # macOS/Linux
venv\Scripts\activate     # Windows
```

It creates a self-contained directory with its own python, pip, and installed packages.

### Step 6: Install Python Dependencies

Open your terminal or command prompt, navigate to your project directory, and install the required Python packages:

```
pip install -r requirements.txt
```

### Step 7: Run Your MCP Server

From your terminal in the project directory, execute your Python script:

```
python job_evaluator.py
```

You should see output indicating that the MCP server is starting on `http://0.0.0.0:8085`. Keep this terminal window open.

### Step 8: Expose Your Server Publicly (Using ngrok)

Puch AI needs to be able to reach your local server. We'll use `ngrok` for this.

1.  Open a **new** terminal window.

2.  Run `ngrok` to tunnel traffic to your server's port:

    ```
    ngrok http 8085
    ```

3.  `ngrok` will provide you with a forwarding URL (e.g., `https://abcdefg.ngrok-free.app`). **Copy this `https` URL.**

### Step 9: Register Your MCP Server with Puch AI

1.  Go back to your WhatsApp conversation with Puch AI.

2.  Send a message to register your MCP server, replacing `YOUR_NGROK_URL` with the `https` URL you copied from `ngrok`:

    ```
    /register_mcp YOUR_NGROK_URL
    ```

    **Example:**

    ```
    /register_mcp [https://abcdefg.ngrok-free.app](https://abcdefg.ngrok-free.app)
    ```

3.  Puch AI should confirm that your MCP server has been registered successfully.

## How to Use the Job Application Assistant

Once your MCP server is registered, you can use a single prompt to Puch AI to initiate the full job application workflow.

**Your Prompt to Puch AI:**

```
Please help me with this job application. I need an evaluation of my fit, a score, and if I'm a strong match, a cover letter as well.
Job Description URL: [Link to Job Description, e.g., https://remoteok.com/remote-jobs/remote-software-engineer-titan-1093216]
```

**What Puch AI will do:**

1.  Puch AI will call your `job_application_assistant` tool on your MCP server.

2.  Your tool will read `my_resume.pdf` and combine its content with the job description and company name into a comprehensive request.

3.  This request is then sent back to Puch AI.

4.  Puch AI will then use its internal AI capabilities to:

    * Evaluate your strengths and weaknesses.

    * Assign a compatibility score out of 10.

    * If the score is above 7.5, generate and provide you with a tailored cover letter.

    * If the score is 7.5 or less, it will inform you that a cover letter will not be generated due to lower compatibility.

Enjoy your automated job application assistant!

## Screenshots

<img width="949" alt="Screenshot 2025-06-18 at 2 15 54 PM" src="https://github.com/user-attachments/assets/c756ca4a-a90c-4503-bf17-b521304282ba" />
<img width="949" alt="Screenshot 2025-06-18 at 2 22 04 PM" src="https://github.com/user-attachments/assets/5f55ab75-8156-4875-adf7-83c27a4a2823" />
<img width="992" alt="Screenshot 2025-06-18 at 2 24 48 PM" src="https://github.com/user-attachments/assets/8b06d568-b06f-42bc-8d3f-3bff00be4d4e" />

