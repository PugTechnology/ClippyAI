# HiveMind GitHub Watchdog

An autonomous, event-driven development loop orchestrating Gemini and Google Jules to continuously analyze, develop, and review this repository. 

## 🏗️ Architecture

This project relies on a Python webhook listener acting as the central state machine. It coordinates three primary AI agents to iterate on the codebase safely and efficiently.

* **The Watchdog (Python/SQLite):** Listens for GitHub Webhook events, translates AI outputs into markdown, and manages the state of all active tasks in a local SQLite database to prevent infinite loops.
* **The Analyst (Gemini 3.1):** Scans the repository structure, open issues, and the `JOURNAL.md` to identify bugs or missing features. It generates a structured JSON execution plan.
* **The Coder (Google Jules):** Triggered by the Watchdog using a Personal Access Token (PAT) to bypass default GitHub Action limits. Jules reads the Analyst's plan, writes the code, and submits a Pull Request.
* **The Reviewer (Gemini 3.1):** Triggered when Jules opens a PR. It reviews the code against project rules, outputs a JSON verdict, which the Watchdog translates into formatted PR comments for Jules to fix.

## 🔄 The Autonomous Loop

1.  **Scan & Plan:** The Analyst is triggered via a cron job or manual webhook. It receives a compressed repository map (not the full codebase) and generates an issue containing an execution plan.
2.  **Code & PR:** The Watchdog assigns the issue to Jules. Jules branches, writes the code, updates `JOURNAL.md`, and opens a PR using a PAT.
3.  **Review & Refine:** * The Watchdog catches the PR creation webhook and sends the diff to the Reviewer.
    * If the Reviewer returns `REQUEST_CHANGES`, the Watchdog translates the JSON into a markdown comment, triggering Jules to try again.
    * *Circuit Breaker:* Jules is allowed a maximum of **3 attempts** per PR. On the 3rd failure, the PR is closed and flagged for human review.
4.  **Merge & Memory:** If the Reviewer returns `APPROVE`, the PR is merged. The Analyst reads the newly updated `JOURNAL.md` and begins the cycle again.

## 🛡️ Core Directives (Agent Rules)

The following rules are hard-coded into the evaluation criteria of the Reviewer agent. Any PR violating these will be immediately rejected.

1.  **The Journal Rule:** Every Pull Request MUST include an update to `JOURNAL.md` summarizing the changes made, the files touched, and the reasoning. This serves as the system's long-term memory.
2.  **The README Lock:** Agents are strictly prohibited from modifying this `README.md` file. Any structural or foundational changes to the project's core directives require manual human approval.
3.  **Context Efficiency:** The Analyst will not attempt to read the entire codebase. It will rely on `tree` directory structures and request specific file contents only when necessary.

## 🚀 Deployment

The Watchdog is designed to run continuously. It requires an exposed endpoint to receive GitHub Webhooks.

### Environment Variables
```env
GITHUB_WEBHOOK_SECRET=your_secret_here
GITHUB_PAT=your_machine_user_token
GEMINI_API_KEY=your_gemini_key
PORT=5000
```

### Local Setup & Testing

1.  **Clone the Repository**
    ```bash
    git clone <your-repo-url>
    cd <your-repo-name>
    ```

2.  **Environment Variables**
    Create a `.env` file based on the provided template:
    ```bash
    cp .env.example .env
    ```
    Then, fill in the values in your `.env` file:
    *   `GITHUB_WEBHOOK_SECRET`: A secret string used to secure your webhook endpoint.
    *   `GITHUB_PAT`: A Personal Access Token for the machine user (e.g., google-jules) with repository access.
    *   `GEMINI_API_KEY`: Your Google Gemini API Key.
    *   `REPO_OWNER`: Your GitHub username or organization name.
    *   `REPO_NAME`: The name of the repository.

3.  **Run with Docker Compose**
    Start the Watchdog server:
    ```bash
    docker-compose up -d --build
    ```
    The server will be running on `http://localhost:5000`.

4.  **Configure GitHub Webhooks**
    *   Go to your GitHub repository -> Settings -> Webhooks -> Add webhook.
    *   **Payload URL:** `http://<your-public-ip-or-domain>:5000/webhook` (You might need a tool like ngrok for local testing).
    *   **Content type:** `application/json`
    *   **Secret:** The `GITHUB_WEBHOOK_SECRET` from your `.env` file.
    *   **Events:** Select "Issue comments" and "Pull requests".
    *   Make sure the webhook is active.

### Triggering the Analyst

You can trigger the Analyst Agent to create an execution plan for an issue in two ways:
1.  **Via GitHub Comment:** Comment `@hivemind` on any open issue.
2.  **Via API:** Send a POST request to `/trigger-analyst/{issue_number}`.
