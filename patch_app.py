with open("app.py", "r") as f:
    code = f.read()

helpers_code = """
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

def get_repo_map():
    response = github_request("GET", "/git/trees/main?recursive=1")
    if response.status_code != 200:
        return "Could not fetch repository map."
    data = response.json()
    tree = data.get("tree", [])
    paths = [item["path"] for item in tree]
    return "\\n".join(paths)

def get_journal_summary():
    response = github_request("GET", "/contents/JOURNAL.md")
    if response.status_code != 200:
        return "No recent history found."
    data = response.json()
    import base64
    content = base64.b64decode(data.get("content", "")).decode("utf-8")
    # Take the last 2000 characters to avoid huge context
    return content[-2000:]
"""

analyst_logic = """
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
    response = model.generate_content(
        full_prompt,
        generation_config=genai.GenerationConfig(response_mime_type="application/json")
    )

    try:
        plan_data = json.loads(response.text)
    except Exception as e:
        print(f"Failed to parse Gemini response: {e}")
        return

    if plan_data.get("should_proceed"):
        # Format the plan into a comment
        plan_steps = "\\n".join([f"1. {step}" for step in plan_data.get("plan", [])])
        files_to_change = "\\n".join([f"- {f}" for f in plan_data.get("files_to_change", [])])
        risks = "\\n".join([f"- {r}" for r in plan_data.get("risks", [])])

        comment_body = (
            f"### 🧠 Analyst Plan Generated\\n\\n"
            f"**Analysis:** {plan_data.get('analysis')}\\n"
            f"**Estimated Complexity:** {plan_data.get('estimated_complexity')}\\n\\n"
            f"#### Files to Modify:\\n{files_to_change}\\n\\n"
            f"#### Execution Plan:\\n{plan_steps}\\n\\n"
            f"#### Instructions for Coder:\\n{plan_data.get('coder_instructions')}\\n\\n"
            f"#### Potential Risks:\\n{risks}\\n\\n"
            f"@google-jules, please begin execution."
        )

        # Post the comment
        github_request("POST", f"/issues/{issue_number}/comments", {"body": comment_body})

        # Assign to coder
        github_request("POST", f"/issues/{issue_number}/assignees", {"assignees": ["google-jules"]})
    else:
        # If should_proceed is false, add a comment explaining why (if they provided an analysis)
        reason = plan_data.get("analysis", "Analyst determined it should not proceed with this request.")
        github_request("POST", f"/issues/{issue_number}/comments", {"body": f"### 🧠 Analyst Note\\n\\n{reason}"})
"""

webhook_updates = """
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
"""

code = code.replace(
    '# Utility: GitHub API Client\ndef github_request(method, endpoint, data=None):\n    headers = {\n        "Authorization": f"Bearer {GITHUB_PAT}",\n        "Accept": "application/vnd.github.v3+json",\n        "X-GitHub-Api-Version": "2022-11-28"\n    }\n    url = f"https://api.github.com/repos/{REPO_OWNER}/{REPO_NAME}{endpoint}"\n    \n    with httpx.Client() as client:\n        if method == "GET":\n            # If fetching a diff, change the accept header\n            if endpoint.endswith(".diff"):\n                headers["Accept"] = "application/vnd.github.v3.diff"\n            return client.get(url, headers=headers)\n        elif method == "POST":\n            return client.post(url, headers=headers, json=data)\n        elif method == "PATCH":\n            return client.patch(url, headers=headers, json=data)',
    helpers_code
)

code = code.replace("# API Endpoints", analyst_logic + "\n# API Endpoints")

code = code.replace(
    '    # Route Pull Request Events\n    if event == "pull_request":\n        action = payload.get("action")\n        pr_number = payload["pull_request"]["number"]\n        sender = payload["sender"]["login"]\n        \n        # Only trigger review loop if the PR was opened or updated by Jules\n        if action in ["opened", "synchronize"] and sender == "google-jules":\n            background_tasks.add_task(process_pr_review, pr_number)\n\n    return {"status": "accepted"}',
    webhook_updates
)

with open("app.py", "w") as f:
    f.write(code)
