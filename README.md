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
