import os
import hmac
import hashlib
import sqlite3
import httpx
import json
import google.generativeai as genai
from fastapi import FastAPI, Request, HTTPException, BackgroundTasks
from contextlib import asynccontextmanager

# Configuration
GITHUB_PAT = os.getenv("GITHUB_PAT")
GITHUB_WEBHOOK_SECRET = os.getenv("GITHUB_WEBHOOK_SECRET")
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")
REPO_OWNER = "your-github-username"
REPO_NAME = "your-repo-name"
MAX_RETRIES = 3

# Initialize Gemini
genai.configure(api_key=GEMINI_API_KEY)
# Using gemini-2.5-flash as the standard fast/capable model
model = genai.GenerativeModel('gemini-2.5-flash')

# Load Static Prompts & Rules
try:
    with open("prompt_reviewer.txt", "r") as f:
        REVIEWER_PROMPT_TEMPLATE = f.read()
except FileNotFoundError:
    REVIEWER_PROMPT_TEMPLATE = "Review this code: {diff} with rules: {rules}"

try:
    with open("README.md", "r") as f:
        PROJECT_RULES = f.read()
except FileNotFoundError:
    PROJECT_RULES = "Standard Python conventions apply."

# Database Initialization
def init_db():
    conn = sqlite3.connect('data/watchdog.db')
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
def github_request(method, endpoint, data=None):
    headers = {
        "Authorization": f"Bearer {GITHUB_PAT}",
        "Accept": "application/vnd.github.v3+json",
        "X-GitHub-Api-Version": "2022-11-28"
    }
    url = f"https://api.github.com/repos/{REPO_OWNER}/{REPO_NAME}{endpoint}"
    
    with httpx.Client() as client:
        if method == "GET":
            # If fetching a diff, change the accept header
            if endpoint.endswith(".diff"):
                headers["Accept"] = "application/vnd.github.v3.diff"
            return client.get(url, headers=headers)
        elif method == "POST":
            return client.post(url, headers=headers, json=data)
        elif method == "PATCH":
            return client.patch(url, headers=headers, json=data)

# Core Logic: Reviewing a PR
def process_pr_review(pr_number: int):
    # 1. Check Circuit Breaker
    conn = sqlite3.connect('data/watchdog.db')
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
    full_prompt = REVIEWER_PROMPT_TEMPLATE.format(diff=diff_text, rules=PROJECT_RULES)
    
    # Force JSON output from Gemini
    response = model.generate_content(
        full_prompt,
        generation_config=genai.GenerationConfig(response_mime_type="application/json")
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

    return {"status": "accepted"}

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=5000)
