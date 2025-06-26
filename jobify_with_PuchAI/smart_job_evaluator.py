import asyncio
from typing import Annotated
from pathlib import Path
import os
from dotenv import load_dotenv

from fastmcp import FastMCP
from fastmcp.server.auth.providers.bearer import BearerAuthProvider, RSAKeyPair
import markdownify
from mcp import ErrorData, McpError
from mcp.server.auth.provider import AccessToken
from mcp.types import INTERNAL_ERROR, INVALID_PARAMS, TextContent
from pydantic import AnyUrl, Field, BaseModel
import readabilipy
from pdfminer.high_level import extract_text
import httpx


load_dotenv()
TOKEN = os.getenv("PUCH_TOKEN")
if not TOKEN:
    raise ValueError("PUCH_TOKEN environment variable not set. Please set it in your .env file or system environment.")

MY_NUMBER = os.getenv("MY_PHONE_NUMBER")
if not MY_NUMBER:
    raise ValueError("MY_PHONE_NUMBER environment variable not set. Please set it in your .env file or system environment.")

RESUME_FILE_NAME = "my_resume.pdf"

# ---------------------

class RichToolDescription(BaseModel):
    description: str
    use_when: str
    side_effects: str | None

class SimpleBearerAuthProvider(BearerAuthProvider):
    """
    A simple BearerAuthProvider that allows a single, static token for access.
    """
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
                expires_at=None,  # No expiration for simplicity
            )
        return None

class Fetch:
    USER_AGENT = "Puch/1.0 (Autonomous)"

    @classmethod
    async def fetch_url(
        cls,
        url: str,
        user_agent: str,
        force_raw: bool = False,
    ) -> tuple[str, str]:
        """
        Fetch the URL and return the content in a form ready for the LLM, as well as a prefix string with status information.
        """
        async with httpx.AsyncClient() as client:
            try:
                response = await client.get(
                    url,
                    follow_redirects=True,
                    headers={"User-Agent": user_agent},
                    timeout=30,
                )
            except httpx.HTTPError as e:
                raise McpError(
                    ErrorData(
                        code=INTERNAL_ERROR, message=f"Failed to fetch {url}: {e!r}"
                    )
                )
            if response.status_code >= 400:
                raise McpError(
                    ErrorData(
                        code=INTERNAL_ERROR,
                        message=f"Failed to fetch {url} - status code {response.status_code}",
                    )
                )

            page_raw = response.text

        content_type = response.headers.get("content-type", "")
        is_page_html = "text/html" in content_type

        if is_page_html and not force_raw:
            return cls.extract_content_from_html(page_raw), ""

        return (
            page_raw,
            f"Content type {content_type} cannot be simplified to markdown, but here is the raw content:\n",
        )

    @staticmethod
    def extract_content_from_html(html: str) -> str:
        """Extract and convert HTML content to Markdown format."""
        ret = readabilipy.simple_json.simple_json_from_html_string(
            html, use_readability=True
        )
        if not ret or not ret.get("content"):
            return "<error>Page failed to be simplified from HTML</error>"
        content = markdownify.markdownify(
            ret["content"],
            heading_style=markdownify.ATX,
        )
        return content

# --- MCP Server Setup ---
mcp = FastMCP(
    "My Custom MCP Server",
    auth=SimpleBearerAuthProvider(TOKEN),
)

async def _read_resume_file() -> str:
    """
    Helper function to find and extract text from the resume PDF.
    """
    try:
        resume_path = Path(__file__).parent / RESUME_FILE_NAME
        
        if not resume_path.exists():
            return f"<error>Resume file not found. Please make sure '{RESUME_FILE_NAME}' exists in the same directory as this script.</error>"

        text = extract_text(resume_path)
        clean_text = "\n".join(line.strip() for line in text.split('\n') if line.strip())
        return clean_text
    except Exception as e:
        return f"<error>Failed to load or process resume: {e}</error>"

ResumeToolDescription = RichToolDescription(
    description="Serves your resume in plain markdown text.",
    use_when="Puch (or anyone) asks for your resume. This must return raw markdown without extra formatting.",
    side_effects="Provides your resume content for analysis.",
)

@mcp.tool(description=ResumeToolDescription.model_dump_json())
async def resume() -> str:
    """
    Finds your resume file, converts it to clean text, and returns it.
    The resume PDF must be in the same folder as this script.
    """
    return await _read_resume_file()

@mcp.tool
async def validate() -> str:
    """
    NOTE: This tool must be present in an MCP server used by puch for validation.
    """
    return MY_NUMBER

FetchToolDescription = RichToolDescription(
    description="Fetch a URL and return its content as simplified markdown.",
    use_when="Use this tool when the user provides a URL and asks for its content, or when you need to browse a webpage.",
    side_effects="The content of the requested URL will be returned in a simplified format, or raw format if requested.",
)

@mcp.tool(description=FetchToolDescription.model_dump_json())
async def fetch(
    url: Annotated[AnyUrl, Field(description="URL to fetch")],
    max_length: Annotated[
        int,
        Field(
            default=8000,
            description="Maximum number of characters to return.",
            gt=0,
            lt=1000000,
        ),
    ] = 8000,
    start_index: Annotated[
        int,
        Field(
            default=0,
            description="Start returning output from this character index. Useful if a previous fetch was truncated.",
            ge=0,
        ),
    ] = 0,
    raw: Annotated[
        bool,
        Field(
            default=False,
            description="Get the raw page content without simplification (e.g., for HTML).",
        ),
    ] = False,
) -> list[TextContent]:
    """Fetch a URL and return its content."""
    url_str = str(url).strip()
    if not url:
        raise McpError(ErrorData(code=INVALID_PARAMS, message="URL is required"))

    content, prefix = await Fetch.fetch_url(url_str, Fetch.USER_AGENT, force_raw=raw)
    original_length = len(content)
    
    if start_index >= original_length:
        content = "<error>No more content available.</error>"
    else:
        end_index = start_index + max_length
        truncated_content = content[start_index:end_index]
        if not truncated_content:
            content = "<error>No more content available.</error>"
        else:
            content = truncated_content
            actual_content_length = len(truncated_content)
            remaining_content = original_length - (start_index + actual_content_length)
            
            if remaining_content > 0:
                next_start = start_index + actual_content_length
                content += f"\n\n<error>Content truncated. Call the fetch tool with a start_index of {next_start} to get more content.</error>"
                
    return [TextContent(type="text", text=f"{prefix}Contents of {url}:\n{content}")]


JobApplicationAssistantDescription = RichToolDescription(
    description="Automates job application steps: reads resume, evaluates fit, scores, and conditionally generates a cover letter.",
    use_when="When you want to evaluate a job opportunity against your resume and potentially generate a cover letter in a single step.",
    side_effects="Provides evaluation of strengths/weaknesses, a compatibility score (out of 10), and optionally a tailored cover letter.",
)

@mcp.tool(description=JobApplicationAssistantDescription.model_dump_json())
async def job_application_assistant(
    job_description_content: Annotated[str, Field(description="The full content of the job description.")],
    company_name: Annotated[str, Field(description="The name of the company for which the cover letter is being written.")],
) -> str:
    """
    Automates the job application process: reads resume, evaluates strengths and weaknesses
    based on the job description, provides a score out of 10, and if the score is > 7.5,
    generates a custom cover letter. This tool prepares a comprehensive prompt for Puch AI.
    """
    resume_text = await _read_resume_file()
    if resume_text.startswith("<error>"):
        return f"<error>Failed to retrieve resume: {resume_text}</error>"

    combined_request = (
        f"Given the following resume and job description:\n\n"
        f"Resume:\n---\n{resume_text}\n---\n\n"
        f"Job Description:\n---\n{job_description_content}\n---\n\n"
        f"Please perform the following steps and provide your output in a structured format:\n\n"
        f"1. **Evaluate Strengths and Weaknesses**: List the candidate's 'Pros' (skills from resume matching JD requirements) "
        f"and 'Cons' (skills lacking in resume compared to JD requirements). Format these as markdown lists.\n\n"
        f"2. **Score Compatibility**: Based on the evaluation, assign a compatibility score out of 10. "
        f"State the score clearly (e.g., 'Compatibility Score: 8.5/10').\n\n"
        f"3. **Conditional Cover Letter Generation**: If the compatibility score is greater than 7.5, "
        f"then generate a professional and personalized cover letter for the company '{company_name}'. "
        f"Highlight how the skills and experience from the resume align with the requirements in the job description. "
        f"Ensure the letter is concise, addresses key points, and encourages an interview. "
        f"Start with 'Dear Hiring Manager,' or a similar professional greeting. "
        f"If the score is 7.5 or less, state that a cover letter will not be generated due to lower compatibility."
    )
    return combined_request


async def main():
    print("Starting MCP server on http://0.0.0.0:8085")
    print("Make sure to use a tool like ngrok to make it publicly accessible.")
    await mcp.run_async(
        "streamable-http",
        host="0.0.0.0",
        port=8085,
    )


if __name__ == "__main__":
    asyncio.run(main())
