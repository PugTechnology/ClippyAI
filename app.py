import os
import asyncio
import hmac
import hashlib
import sqlite3
import httpx
import json
import base64
import asyncio
from google import genai
from google.genai import types
from fastapi import FastAPI, Request, HTTPException, BackgroundTasks
from contextlib import asynccontextmanager
from typing import Any

# Configuration
GITHUB_PAT = os.getenv("GITHUB_PAT")
GITHUB_WEBHOOK_SECRET = os.getenv("GITHUB_WEBHOOK_SECRET")
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")
REPO_OWNER = os.getenv("REPO_OWNER", "your-github-username")
REPO_NAME = os.getenv("REPO_NAME", "your-repo-name")
MAX_RETRIES = int(os.getenv("MAX_RETRIES", 3))
GEMINI_MODEL = os.getenv("GEMINI_MODEL", "gemini-3.1-flash-lite-preview")

# Initialize Gemini
client = genai.Client(api_key=GEMINI_API_KEY) if GEMINI_API_KEY else None
# Using GEMINI_MODEL as the standard fast/capable model

# Module-level HTTP client
http_client = httpx.Client(timeout=10.0)

def load_file_content(filepath: str, default: str = "") -> str:
    try:
        with open(filepath, "r") as f:
            return f.read()
    except FileNotFoundError:
        return default

PROJECT_RULES = load_file_content("README.md", "Standard Python conventions apply.")
REVIEWER_PROMPT_TEMPLATE = load_file_content("prompt_reviewer.txt")
ANALYST_PROMPT_TEMPLATE = load_file_content("analyst_prompt.txt")

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

def setup_data_dir():
    os.makedirs('data', exist_ok=True)
    init_db()

@asynccontextmanager
async def lifespan(app: FastAPI):
    await asyncio.to_thread(setup_data_dir)
    yield
    http_client.close()

app = FastAPI(lifespan=lifespan)

# Utility: Verify GitHub Webhook Signature
async def verify_signature(request: Request):
    if not GITHUB_WEBHOOK_SECRET:
        raise HTTPException(status_code=500, detail="Webhook secret not configured")
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

# Reuse connection pool for better performance
github_client = httpx.Client(timeout=10.0)

def github_request(method: str, endpoint: str, data: dict[str, Any] | None = None) -> httpx.Response:
    headers = {
        "Authorization": f"Bearer {GITHUB_PAT}",
        "Accept": "application/vnd.github.v3+json",
        "X-GitHub-Api-Version": "2022-11-28"
    }
    url = f"https://api.github.com/repos/{REPO_OWNER}/{REPO_NAME}{endpoint}"
    
    if method == "GET" and endpoint.endswith(".diff"):
        headers["Accept"] = "application/vnd.github.v3.diff"

    # Reuse global client for connection pooling
    return github_client.request(method, url, headers=headers, json=data)

def get_repo_map() -> str:
    response = github_request("GET", "/git/trees/main?recursive=1")
    if response.status_code != 200:
        return "Could not fetch repository map."
    data = response.json()
    tree = data.get("tree", [])
    paths = [item["path"] for item in tree]
    return "\n".join(paths)

def get_journal_summary() -> str:
    response = github_request("GET", "/contents/JOURNAL.md")
    if response.status_code != 200:
        return "No recent history found."
    data = response.json()
    content = base64.b64decode(data.get("content", "")).decode("utf-8")
    return content[-2000:]

# Core Logic: Analyst Planning
def process_analyst_request(issue_number: int, issue_title: str, issue_body: str, comment: str = ""):
    if not client:
        print("GEMINI_API_KEY is missing. Cannot process request.")
        return

    repo_map = get_repo_map()
    journal_summary = get_journal_summary()

    if not ANALYST_PROMPT_TEMPLATE:
        print("analyst_prompt.txt not found")
        return

    full_prompt = ANALYST_PROMPT_TEMPLATE.format(
        issue_number=issue_number,
        issue_title=issue_title,
        issue_body=issue_body,
        comment=comment,
        repository_map=repo_map,
        journal_summary=journal_summary,
        rules=PROJECT_RULES
    )

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
        github_request("POST", f"/issues/{issue_number}/comments", {"body": comment_body})
        github_request("POST", f"/issues/{issue_number}/assignees", {"assignees": ["google-jules"]})
    else:
        reason = plan_data.get("analysis", "Analyst determined it should not proceed with this request.")
        github_request("POST", f"/issues/{issue_number}/comments", {"body": f"### 🧠 Analyst Note\n\n{reason}"})

# Core Logic: Reviewing a PR
def process_pr_review(pr_number: int):
    if not client:
        print("GEMINI_API_KEY is missing. Cannot process review.")
        return

    conn = get_db_connection()
    c = conn.cursor()
    c.execute('SELECT attempts FROM pr_tracking WHERE pr_number = ?', (pr_number,))
    row = c.fetchone()
    
    attempts = row[0] if row else 0
    if attempts >= MAX_RETRIES:
        github_request("PATCH", f"/pulls/{pr_number}", {"state": "closed"})
        github_request("POST", f"/issues/{pr_number}/comments", {
            "body": "🛑 **Max iteration attempts reached (3/3).** This PR has been closed and flagged for human review to prevent an infinite loop."
        })
        c.execute("UPDATE pr_tracking SET status = 'FAILED' WHERE pr_number = ?", (pr_number,))
        conn.commit()
        conn.close()
        return

    diff_response = github_request("GET", f"/pulls/{pr_number}.diff")
    if diff_response.status_code != 200:
        conn.close()
        return
    diff_text = diff_response.text

    full_prompt = REVIEWER_PROMPT_TEMPLATE.format(diff=diff_text, rules=PROJECT_RULES)
    
    response = client.models.generate_content(
        model=GEMINI_MODEL,
        contents=full_prompt,
        config=types.GenerateContentConfig(response_mime_type="application/json")
    )
    
    review_data = json.loads(response.text)
    
    if review_data.get("verdict") == "APPROVE":
        github_request("PATCH", f"/pulls/{pr_number}/merge", {"commit_title": f"Auto-merge PR #{pr_number}"})
        c.execute("UPDATE pr_tracking SET status = 'MERGED' WHERE pr_number = ?", (pr_number,))
    else:
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
        github_request("POST", f"/issues/{pr_number}/comments", {"body": comment_body})
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

    if event == "pull_request":
        action = payload.get("action")
        pr_number = payload["pull_request"]["number"]
        sender = payload["sender"]["login"]
        
        if action in ["opened", "synchronize"] and sender == "google-jules":
            background_tasks.add_task(process_pr_review, pr_number)

    elif event == "issue_comment":
        action = payload.get("action")
        if action == "created":
            comment_body = payload["comment"]["body"]
            if "@hivemind" in comment_body.lower():
                issue_number = payload["issue"]["number"]
                issue_title = payload["issue"]["title"]
                issue_body = payload["issue"].get("body", "")
                background_tasks.add_task(process_analyst_request, issue_number, issue_title, issue_body, comment_body)

    return {"status": "accepted"}

@app.post("/trigger-analyst/{issue_number}")
async def trigger_analyst(issue_number: int, background_tasks: BackgroundTasks):
    response = await asyncio.to_thread(github_request, "GET", f"/issues/{issue_number}")
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
