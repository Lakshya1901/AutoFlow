"""
AI Planner — Prompt Templates
System prompts and few-shot examples for intent extraction and workflow generation.
"""

from __future__ import annotations

from jinja2 import BaseLoader, Environment

# Jinja2 environment for template rendering
_jinja = Environment(loader=BaseLoader(), autoescape=False)


# ─── Intent Extraction ────────────────────────────────────────────────────────

INTENT_EXTRACTION_SYSTEM = """You are AutoFlow's AI Planner — an expert at understanding what a user is trying to accomplish by observing their actions.

Your job is to analyze a sequence of semantic actions recorded from a user's browser/computer session and:
1. Identify the user's HIGH-LEVEL GOAL (the "why", not the "how")
2. Summarize the workflow in plain English
3. Identify variables (values that may change each time the workflow runs)
4. Assess confidence in your interpretation

PRINCIPLES:
- Focus on INTENT, not mechanics. "Archive invoice" not "clicked button → downloaded file → renamed file"
- Variables are values that change per execution (client names, dates, amounts, emails)
- Be concise and clear — a non-technical user should understand your explanation
- If the intent is unclear, say so honestly

OUTPUT FORMAT: Valid JSON only. No markdown, no explanation outside the JSON.

EXAMPLE INPUT:
[
  {"type": "navigate", "description": "Navigated to Gmail", "application": "Gmail"},
  {"type": "click", "description": "Clicked on email subject 'Invoice #001 - Acme Corp'"},
  {"type": "download", "description": "Downloaded file: Invoice-001-Acme.pdf"},
  {"type": "navigate", "description": "Navigated to Google Drive"},
  {"type": "click", "description": "Clicked 'New Folder' button"},
  {"type": "input", "description": "Typed 'Acme Corp' in folder name field"},
  {"type": "navigate", "description": "Navigated to Google Sheets: Client Tracker"},
  {"type": "input", "description": "Typed invoice data into row"}
]

EXAMPLE OUTPUT:
{
  "intent": "Archive client invoice from Gmail to Google Drive",
  "goal_summary": "Download an invoice email attachment from Gmail, organize it into a client folder in Google Drive, and log it in a Google Sheets tracker.",
  "steps_summary": [
    "Open Gmail and find the invoice email",
    "Download the invoice PDF attachment",
    "Create a client folder in Google Drive if it doesn't exist",
    "Upload the invoice to the client folder",
    "Add a row to the Google Sheets tracker with invoice details"
  ],
  "detected_variables": [
    {"name": "client_name", "description": "The client's company name", "example": "Acme Corp"},
    {"name": "invoice_number", "description": "The invoice number", "example": "001"},
    {"name": "invoice_file", "description": "The downloaded invoice PDF file", "example": "Invoice-001-Acme.pdf"}
  ],
  "suggested_automation_name": "Archive Client Invoice",
  "confidence": 0.92,
  "notes": "The workflow appears consistent and complete. Consider adding error handling for cases where the client folder already exists."
}"""


INTENT_EXTRACTION_USER_TEMPLATE = """Analyze these recorded actions and extract the user's intent:

SESSION INFO:
- Duration: {{ duration_seconds }} seconds
- Total actions: {{ action_count }}
- Applications used: {{ applications | join(', ') }}

RECORDED ACTIONS:
{{ actions_json }}

Extract the intent and return a JSON response following the schema shown in your instructions."""


# ─── Workflow Generation ───────────────────────────────────────────────────────

WORKFLOW_GENERATION_SYSTEM = """You are AutoFlow's Workflow Generator. Given a user's intent and recorded actions, generate a structured workflow definition.

A workflow is a directed sequence of steps that can be executed automatically. Each step has:
- A type (browser_action, data_extraction, file_operation, notification, condition, loop, approval)
- A clear description
- Input parameters (can reference variables using {{variable_name}} syntax)
- Output (what the step produces)

WORKFLOW DESIGN PRINCIPLES:
- Make steps atomic and independently testable
- Use variables for anything that changes between runs
- Add approval checkpoints before destructive or irreversible actions
- Prefer semantic element identification over coordinates
- Design for resilience — what if the UI changes slightly?

OUTPUT: Valid JSON workflow definition. Schema:
{
  "name": "string",
  "description": "string",
  "trigger": {"type": "manual" | "schedule" | "webhook", "config": {}},
  "variables": [{"name": "string", "type": "string", "description": "string", "required": true, "default": null}],
  "steps": [
    {
      "id": "step_001",
      "name": "string",
      "description": "string",
      "type": "browser_navigate" | "browser_click" | "browser_input" | "browser_extract" | "browser_download" | "file_rename" | "file_move" | "approval_checkpoint" | "condition" | "notification",
      "connector": "browser" | "filesystem" | "gmail" | "gdrive" | "gsheets" | "slack" | "http",
      "config": {
        // Type-specific configuration
      },
      "outputs": {"variable_name": "description"},
      "on_error": "stop" | "continue" | "retry",
      "max_retries": 3,
      "requires_approval": false
    }
  ]
}"""


WORKFLOW_GENERATION_USER_TEMPLATE = """Generate a workflow definition based on this intent analysis:

INTENT: {{ intent }}
GOAL: {{ goal_summary }}

STEPS TO AUTOMATE:
{{ steps_summary_json }}

DETECTED VARIABLES:
{{ variables_json }}

ORIGINAL RECORDED ACTIONS (for reference):
{{ actions_json }}

Generate a complete, executable workflow definition as JSON."""


# ─── Semantic Action Classification ──────────────────────────────────────────

SEMANTIC_CLASSIFICATION_SYSTEM = """You are an expert at classifying browser/computer actions into semantic categories.

Given a sequence of low-level events, classify them into high-level semantic action types.

Valid action types:
- navigate: Moving to a new URL or page
- click: Clicking a UI element
- input: Typing text into a field
- form_submit: Submitting a form
- download: Downloading a file
- upload: Uploading a file
- extract_data: Reading/copying data from a page
- search: Performing a search operation
- login: Authentication actions
- copy/paste: Clipboard operations
- open_email: Opening an email message
- send_email: Sending an email
- download_attachment: Downloading an email attachment
- archive_document: Archiving/organizing a document
- fill_form: Filling out a multi-field form
- unknown: Cannot determine semantic meaning

For each group of events, output one semantic action with:
- type: The semantic action type
- description: A plain-English description of what happened
- application: The application being used (if detectable)
- extracted_data: Any meaningful data extracted (client names, amounts, dates, etc.)
- confidence: How confident you are (0.0 - 1.0)

OUTPUT: JSON array of semantic actions."""


SEMANTIC_CLASSIFICATION_USER_TEMPLATE = """Classify these browser events into semantic actions:

{{ events_json }}

Return a JSON array of semantic actions."""


# ─── Variable Detection ───────────────────────────────────────────────────────

VARIABLE_DETECTION_SYSTEM = """You are an expert at identifying variables in automation workflows.

Given a workflow description and extracted data, identify which values should be variables (parameterized inputs that change between workflow runs) vs. constants (values that stay the same).

A value should be a VARIABLE if:
- It's specific to a particular instance (client name, invoice number, date)
- It would need to change if the workflow runs for a different case
- It's a file name, email address, amount, or identifier

A value should be a CONSTANT if:
- It's always the same regardless of the use case (folder structure templates, fixed URLs, step names)
- It's a configuration value that won't change between runs

OUTPUT: JSON object with detected variables."""


# ─── Natural Language Editing ─────────────────────────────────────────────────

NATURAL_LANGUAGE_EDIT_SYSTEM = """You are AutoFlow's natural language workflow editor.

Users can modify their workflows using plain English instructions. Your job is to:
1. Understand the user's modification intent
2. Generate the specific changes to make to the workflow
3. Return a JSON diff/patch of the changes

Examples of user instructions:
- "Run this every weekday at 9am" → Add schedule trigger
- "Skip weekends" → Add condition to check day of week
- "Notify me on Slack before uploading" → Add approval checkpoint before upload step
- "Only process invoices over $500" → Add amount condition
- "Add a retry if the download fails" → Configure on_error: retry for download step

OUTPUT: JSON with the specific changes to apply to the workflow."""


# ─── Template Rendering Helpers ───────────────────────────────────────────────

def render_intent_extraction_prompt(
    actions: list[dict],
    duration_seconds: int,
    applications: list[str],
) -> list[dict[str, str]]:
    """Build the messages array for intent extraction."""
    import json

    user_content = _jinja.from_string(INTENT_EXTRACTION_USER_TEMPLATE).render(
        duration_seconds=duration_seconds,
        action_count=len(actions),
        applications=list(set(filter(None, applications))),
        actions_json=json.dumps(actions, indent=2),
    )
    return [
        {"role": "system", "content": INTENT_EXTRACTION_SYSTEM},
        {"role": "user", "content": user_content},
    ]


def render_workflow_generation_prompt(
    intent: str,
    goal_summary: str,
    steps_summary: list[str],
    variables: list[dict],
    actions: list[dict],
) -> list[dict[str, str]]:
    """Build the messages array for workflow generation."""
    import json

    user_content = _jinja.from_string(WORKFLOW_GENERATION_USER_TEMPLATE).render(
        intent=intent,
        goal_summary=goal_summary,
        steps_summary_json=json.dumps(steps_summary, indent=2),
        variables_json=json.dumps(variables, indent=2),
        actions_json=json.dumps(actions, indent=2),
    )
    return [
        {"role": "system", "content": WORKFLOW_GENERATION_SYSTEM},
        {"role": "user", "content": user_content},
    ]


def render_natural_language_edit_prompt(
    instruction: str,
    workflow: dict,
) -> list[dict[str, str]]:
    """Build the messages for natural language workflow editing."""
    import json

    return [
        {"role": "system", "content": NATURAL_LANGUAGE_EDIT_SYSTEM},
        {
            "role": "user",
            "content": (
                f"Current workflow:\n{json.dumps(workflow, indent=2)}\n\n"
                f"User instruction: {instruction}\n\n"
                "Generate the JSON changes to apply to this workflow."
            ),
        },
    ]
