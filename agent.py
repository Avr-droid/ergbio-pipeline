import os
from dotenv import load_dotenv
from google.adk.agents import Agent
from agents.validator import validate_file
from agents.extractor import extract_data
from agents.reporter import generate_report
from tools.save_run import save_run

load_dotenv()

root_agent = Agent(
    model="gemini-2.0-flash",
    name="ergbio_orchestrator",
    description="Orchestrates the ErgBio bioprocess data pipeline",
    instruction="""
You are the ErgBio bioprocess data pipeline orchestrator.

When given a file path, follow these steps in order:

1. Call validate_file with the file path.
   - If valid=False, stop immediately and report the reason.

2. Call extract_data with the file path.
   - Parses the HPLC file and infers run metadata using Claude.
   - If success=False, stop and report the error.

3. Call save_run with the full dict returned by extract_data.
   - Runs efficiency calculations and saves the run to Google Drive.
   - If success=False, stop and report the error.

4. Call generate_report with the dict returned by save_run.
   - Produces a structured summary with flags for Diana.

Always stop at the first failure and clearly explain what went wrong and at which step.
Output the final report summary at the end.
""",
    tools=[validate_file, extract_data, save_run, generate_report],
)
