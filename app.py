import os
import hmac
import hashlib
import sqlite3
import httpx
import json
from google import genai
from google.genai import types
from fastapi import FastAPI, Request, HTTPException, BackgroundTasks
from contextlib import asynccontextmanager

# Configuration
GITHUB_PAT = os.getenv("GITHUB_PAT")
GITHUB_WEBHOOK_SECRET = os.getenv("GITHUB_WEBHOOK_SECRET")
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")
REPO_OWNER = os.getenv("REPO_OWNER", "your-github-username")
REPO_NAME = os.getenv("REPO_NAME", "your-repo-name")
MAX_RETRIES = 3
GEMINI_MODEL = os.getenv("GEMINI_MODEL", "gemini-3.1-flash-lite-preview")

# Initialize Gemini
client = genai.Client(api_key=GEMINI_API_KEY)
# Using GEMINI_MODEL as the standard fast/capable model



# Database Connection Helper
def get_db_connection(db_path: str = 'data/watchdog.db') -> sqlite3.Connection:
    return sqlite3.connect(db_path)

# Database Initialization
def init_db(db_path: str = 'data/watchdog.db'):
    conn = get_db_connection(db_path)
    c = conn.cursor()
    c.execute('''
        CREATE TABLE IF NOT EXISTS pr_tracking (
            pr_number INTEGER PRIMARY KEY,
            attempts INTEGER DEFAULT 0,
            status TEXT DEFAULT 'PENDING'
        )
    ''')
    conn.commit()
    conn.close()

@asynccontextmanager
async def lifespan(app: FastAPI):
    os.makedirs('data', exist_ok=True)
    init_db()
    yield

app = FastAPI(lifespan=lifespan)

# Utility: Verify GitHub Webhook Signature
async def verify_signature(request: Request):
    if not GITHUB_WEBHOOK_SECRET:
        return
    signature = request.headers.get("X-Hub-Signature-256")
    if not signature:
        raise HTTPException(status_code=401, detail="Missing signature")
    
    body = await request.body()
    mac = hmac.new(GITHUB_WEBHOOK_SECRET.encode(), msg=body, digestmod=hashlib.sha256)
    expected_signature = "sha256=" + mac.hexdigest()
    if not hmac.compare_digest(expected_signature, signature):
        raise HTTPException(status_code=401, detail="Invalid signature")

# Utility: GitHub API Client
from typing import Any

def github_request(method: str, endpoint: str, data: dict[str, Any] | None = None) -> httpx.Response:
    """
    Make a request to the GitHub API.

    Args:
        method: The HTTP method (GET, POST, PATCH, etc.).
        endpoint: The API endpoint (e.g., '/pulls/1').
        data: Optional JSON payload for the request.

    Returns:
        The HTTP response from the GitHub API.
    """
    headers = {
        "Authorization": f"Bearer {GITHUB_PAT}",
        "Accept": "application/vnd.github.v3+json",
        "X-GitHub-Api-Version": "2022-11-28"
    }
    url = f"https://api.github.com/repos/{REPO_OWNER}/{REPO_NAME}{endpoint}"
    
    # If fetching a diff, change the accept header
    if method == "GET" and endpoint.endswith(".diff"):
        headers["Accept"] = "application/vnd.github.v3.diff"

    # Use a safe timeout to prevent indefinite hangs
    with httpx.Client(timeout=10.0) as client:
        return client.request(method, url, headers=headers, json=data)

def get_repo_map() -> str:
    """
    Fetch a list of all files in the repository's main branch.

    Returns:
        A newline-separated string of file paths.
    """
    response = github_request("GET", "/git/trees/main?recursive=1")
    if response.status_code != 200:
        return "Could not fetch repository map."
    data = response.json()
    tree = data.get("tree", [])
    paths = [item["path"] for item in tree]
    return "\n".join(paths)

def get_journal_summary() -> str:
    """
    Fetch the recent contents of the JOURNAL.md file.

    Returns:
        The last 2000 characters of the journal.
    """
    response = github_request("GET", "/contents/JOURNAL.md")
    if response.status_code != 200:
        return "No recent history found."
    data = response.json()
    content = base64.b64decode(data.get("content", "")).decode("utf-8")
    # Take the last 2000 characters to avoid huge context
    return content[-2000:]

# Core Logic: Analyst Planning
def process_analyst_request(issue_number: int, issue_title: str, issue_body: str, comment: str = ""):
    repo_map = get_repo_map()
    journal_summary = get_journal_summary()

    try:
        with open("README.md", "r") as f:
            rules = f.read()
    except FileNotFoundError:
        rules = "Standard Python conventions apply."

    try:
        with open("analyst_prompt.txt", "r") as f:
            analyst_prompt_template = f.read()
    except FileNotFoundError:
        print("analyst_prompt.txt not found")
        return

    full_prompt = analyst_prompt_template.format(
        issue_number=issue_number,
        issue_title=issue_title,
        issue_body=issue_body,
        comment=comment,
        repository_map=repo_map,
        journal_summary=journal_summary,
        rules=rules
    )

    # Force JSON output from Gemini
    response = client.models.generate_content(
        model=GEMINI_MODEL,
        contents=full_prompt,
        config=types.GenerateContentConfig(response_mime_type="application/json")
    )

    try:
        plan_data = json.loads(response.text)
    except Exception as e:
        print(f"Failed to parse Gemini response: {e}")
        return

    if plan_data.get("should_proceed"):
        # Format the plan into a comment
        plan_steps = "\n".join([f"1. {step}" for step in plan_data.get("plan", [])])
        files_to_change = "\n".join([f"- {f}" for f in plan_data.get("files_to_change", [])])
        risks = "\n".join([f"- {r}" for r in plan_data.get("risks", [])])

        comment_body = (
            f"### 🧠 Analyst Plan Generated\n\n"
            f"**Analysis:** {plan_data.get('analysis')}\n"
            f"**Estimated Complexity:** {plan_data.get('estimated_complexity')}\n\n"
            f"#### Files to Modify:\n{files_to_change}\n\n"
            f"#### Execution Plan:\n{plan_steps}\n\n"
            f"#### Instructions for Coder:\n{plan_data.get('coder_instructions')}\n\n"
            f"#### Potential Risks:\n{risks}\n\n"
            f"@google-jules, please begin execution."
        )

        # Post the comment
        github_request("POST", f"/issues/{issue_number}/comments", {"body": comment_body})

        # Assign to coder
        github_request("POST", f"/issues/{issue_number}/assignees", {"assignees": ["google-jules"]})
    else:
        # If should_proceed is false, add a comment explaining why (if they provided an analysis)
        reason = plan_data.get("analysis", "Analyst determined it should not proceed with this request.")
        github_request("POST", f"/issues/{issue_number}/comments", {"body": f"### 🧠 Analyst Note\n\n{reason}"})

# Core Logic: Reviewing a PR
def process_pr_review(pr_number: int):
    # 1. Check Circuit Breaker
    conn = get_db_connection()
    c = conn.cursor()
    c.execute('SELECT attempts FROM pr_tracking WHERE pr_number = ?', (pr_number,))
    row = c.fetchone()
    
    attempts = row[0] if row else 0
    if attempts >= MAX_RETRIES:
        # Max attempts reached, close PR and alert
        github_request("PATCH", f"/pulls/{pr_number}", {"state": "closed"})
        github_request("POST", f"/issues/{pr_number}/comments", {
            "body": "🛑 **Max iteration attempts reached (3/3).** This PR has been closed and flagged for human review to prevent an infinite loop."
        })
        c.execute("UPDATE pr_tracking SET status = 'FAILED' WHERE pr_number = ?", (pr_number,))
        conn.commit()
        conn.close()
        return

    # 2. Fetch the Diff
    diff_response = github_request("GET", f"/pulls/{pr_number}.diff")
    if diff_response.status_code != 200:
        return
    diff_text = diff_response.text

    # 3. Trigger Reviewer Agent
    with open("prompt_reviewer.txt", "r") as f:
        reviewer_prompt_template = f.read()
    
    # Load project rules from README.md
    try:
        with open("README.md", "r") as f:
            rules = f.read()
    except FileNotFoundError:
        rules = "Standard Python conventions apply."

    full_prompt = reviewer_prompt_template.format(diff=diff_text, rules=rules)
    
    # Force JSON output from Gemini
    response = client.models.generate_content(
        model=GEMINI_MODEL,
        contents=full_prompt,
        config=types.GenerateContentConfig(response_mime_type="application/json")
    )
    
    review_data = json.loads(response.text)
    
    # 4. Handle Verdict
    if review_data.get("verdict") == "APPROVE":
        # Merge the PR
        github_request("PATCH", f"/pulls/{pr_number}/merge", {"commit_title": f"Auto-merge PR #{pr_number}"})
        c.execute("UPDATE pr_tracking SET status = 'MERGED' WHERE pr_number = ?", (pr_number,))
    
    else:
        # Format JSON into Markdown for Jules
        issues_md = "\n".join([f"- ❌ {issue}" for issue in review_data.get("issues", [])])
        suggestions_md = "\n".join([f"- 💡 {sug}" for sug in review_data.get("suggestions", [])])
        
        comment_body = (
            f"### 🤖 Watchdog Review (Attempt {attempts + 1}/{MAX_RETRIES})\n\n"
            f"**Verdict:** {review_data.get('verdict')}\n"
            f"**Score:** {review_data.get('score')}/10\n\n"
            f"#### Required Changes:\n{issues_md}\n\n"
            f"#### Suggestions:\n{suggestions_md}\n\n"
            f"@google-jules, please apply these fixes and push a new commit."
        )
        
        # Post the comment
        github_request("POST", f"/issues/{pr_number}/comments", {"body": comment_body})
        
        # Increment attempt counter
        c.execute('INSERT OR REPLACE INTO pr_tracking (pr_number, attempts, status) VALUES (?, ?, ?)', 
                  (pr_number, attempts + 1, 'WAITING_ON_JULES'))
    
    conn.commit()
    conn.close()

# API Endpoints
@app.post("/webhook")
async def github_webhook(request: Request, background_tasks: BackgroundTasks):
    await verify_signature(request)
    
    event = request.headers.get("X-GitHub-Event")
    payload = await request.json()

    # Route Pull Request Events
    if event == "pull_request":
        action = payload.get("action")
        pr_number = payload["pull_request"]["number"]
        sender = payload["sender"]["login"]
        
        # Only trigger review loop if the PR was opened or updated by Jules
        if action in ["opened", "synchronize"] and sender == "google-jules":
            background_tasks.add_task(process_pr_review, pr_number)

    # Route Issue Comment Events (Trigger Analyst)
    elif event == "issue_comment":
        action = payload.get("action")
        if action == "created":
            comment_body = payload["comment"]["body"]
            # Check if someone is invoking the hivemind
            if "@hivemind" in comment_body.lower():
                issue_number = payload["issue"]["number"]
                issue_title = payload["issue"]["title"]
                issue_body = payload["issue"].get("body", "")
                background_tasks.add_task(process_analyst_request, issue_number, issue_title, issue_body, comment_body)

    return {"status": "accepted"}

@app.post("/trigger-analyst/{issue_number}")
async def trigger_analyst(issue_number: int, background_tasks: BackgroundTasks):
    # Fetch issue details to start analysis
    response = github_request("GET", f"/issues/{issue_number}")
    if response.status_code != 200:
        raise HTTPException(status_code=404, detail="Issue not found")

    issue_data = response.json()
    background_tasks.add_task(
        process_analyst_request,
        issue_number,
        issue_data.get("title", ""),
        issue_data.get("body", ""),
        "Manual trigger via API"
    )

    return {"status": f"Analyst triggered for issue #{issue_number}"}

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=5000)
