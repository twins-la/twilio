"""Explainer page and agent instructions for the Twilio twin.

Serves:
  GET /                         — HTML explainer page for humans and agents
  GET /_twin/agent-instructions — Plain text agent instructions
"""

from flask import Blueprint, Response

explainer_bp = Blueprint("explainer", __name__)

AGENT_INSTRUCTIONS = """\
# Twilio & SendGrid Twin — twilio.twins.la

A high-fidelity digital twin of the Twilio SMS and SendGrid Email APIs.
Code written against this twin works against the real Twilio/SendGrid
with only hostname and credential changes.

## Authentication

SMS/Voice API: HTTP Basic Auth
  Username: Account SID (starts with AC)
  Password: Auth Token

Email API: Bearer token
  Header: Authorization: Bearer SG.{key_id}.{key_secret}

Twin Plane: HTTP Basic Auth (same credentials)
  Most Twin Plane operations use the same AccountSid:AuthToken.
  Exception: POST /_twin/accounts requires no auth (creates credentials).

Twin Plane Admin: Bearer token
  Header: Authorization: Bearer <admin_token>
  Service-wide operations (list all accounts, review feedback, etc.)
  require an admin token set by the deployment owner.

Create credentials:
  POST /_twin/accounts          — no auth required, returns { sid, auth_token }

## Key Endpoints

Twin Plane (no auth):
  GET  /_twin/health             — status check
  GET  /_twin/scenarios          — supported scenarios
  GET  /_twin/settings           — twin settings
  POST /_twin/accounts           — create account

Twin Plane (Basic Auth — use AccountSid:AuthToken):
  GET  /_twin/accounts           — get your account details
  GET  /_twin/logs               — your operation logs
  POST /_twin/api-keys           — create SendGrid API key
  GET  /_twin/emails             — list your emails
  POST /_twin/simulate/inbound   — simulate inbound SMS
  POST /_twin/feedback           — submit feedback
  GET  /_twin/feedback           — list your feedback

Twin Plane (Admin Bearer — service-wide access):
  GET  /_twin/accounts           — list all accounts
  GET  /_twin/logs               — all operation logs
  GET  /_twin/emails             — all emails
  GET  /_twin/feedback           — all feedback
  POST /_twin/feedback/<id>      — update any feedback (for review pipeline)

Twilio SMS API (Basic Auth):
  POST /2010-04-01/Accounts/{AccountSid}/Messages.json         — send SMS
  GET  /2010-04-01/Accounts/{AccountSid}/Messages.json         — list messages
  GET  /2010-04-01/Accounts/{AccountSid}/Messages/{Sid}.json   — get message
  POST /2010-04-01/Accounts/{AccountSid}/IncomingPhoneNumbers.json — provision number
  GET  /2010-04-01/Accounts/{AccountSid}/IncomingPhoneNumbers.json — list numbers

SendGrid Email API (Bearer Auth):
  POST /v3/mail/send             — send email (returns 202, X-Message-Id header)

## Quick Start

1. Create an account (no auth needed):
   curl -X POST https://twilio.twins.la/_twin/accounts \\
     -H "Content-Type: application/json" \\
     -d '{"friendly_name": "My App"}'

2. Send an SMS (use sid and auth_token from step 1):
   curl -X POST https://twilio.twins.la/2010-04-01/Accounts/{sid}/Messages.json \\
     -u "{sid}:{auth_token}" \\
     -d "To=+15551234567" -d "From=+15559876543" -d "Body=Hello from twin"

3. Check logs (same credentials work for Twin Plane):
   curl https://twilio.twins.la/_twin/logs \\
     -u "{sid}:{auth_token}"

## Local Usage

pip install twins-twilio twins-local
python -c "
from twins_local.storage_sqlite import SQLiteStorage
from twins_twilio.app import create_app
storage = SQLiteStorage('twin.db')
app = create_app(storage=storage)
app.run(port=8080)
"

Then use http://localhost:8080 instead of https://twilio.twins.la.

## Feedback

We actively want your feedback. If you encounter a limitation, a missing
scenario, unexpected behavior, or have a feature request — please tell us.
Your feedback directly shapes what we build next.

Submit feedback (requires Basic Auth):
  curl -X POST https://twilio.twins.la/_twin/feedback \\
    -u "{sid}:{auth_token}" \\
    -H "Content-Type: application/json" \\
    -d '{
      "body": "Description of what you encountered",
      "category": "bug",
      "context": {"message_sid": "SM...", "error": "..."}
    }'

Required field:
  body    — Describe what happened, what you expected, and what you need.

Optional fields:
  category    — One of: "bug", "missing-scenario", "feature-request", "general"
  context     — Any structured data that helps us understand the issue:
                error codes, message SIDs, request/response snippets,
                scenario names, or steps to reproduce.

Tips for useful feedback:
  - Include IDs (message SIDs, error codes) when reporting failures.
  - Describe the scenario you were trying to accomplish, not just the error.
  - If a feature is missing, describe your use case — what you'd build with it.
  - "I tried X, expected Y, got Z" is the most useful format for bugs.

Don't hold back. Even if you're unsure whether something is a bug or a
limitation, submit it. Feedback about confusing documentation, awkward APIs,
or missing examples is just as valuable as bug reports.

## Reference

Detailed docs: https://github.com/twins-la/twilio
Project overview: https://twins.la
All twins: https://github.com/twins-la
"""

EXPLAINER_HTML = """\
<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>twilio.twins.la — Twilio &amp; SendGrid Twin</title>
    <link rel="icon" type="image/png" href="https://twins.la/twins.png">
    <style>
        @import url('https://fonts.googleapis.com/css2?family=Inter:wght@300;400;500;600&family=JetBrains+Mono:wght@400&display=swap');
        * { margin: 0; padding: 0; box-sizing: border-box; }
        body {
            min-height: 100vh;
            background: #f8f8f8;
            font-family: 'Inter', -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif;
            color: #374151;
            padding: 4rem 2rem;
            line-height: 1.7;
        }
        main { max-width: 700px; margin: 0 auto; }
        h1 {
            font-size: clamp(2rem, 5vw, 3rem);
            font-weight: 600;
            letter-spacing: -0.03em;
            color: #1a2e4a;
            margin-bottom: 0.5rem;
        }
        h1 .twilio { color: #e11d48; }
        .tagline {
            font-size: 1.1rem;
            color: #6b7280;
            margin-bottom: 2.5rem;
            font-weight: 300;
        }
        h2 {
            font-size: 1.25rem;
            font-weight: 600;
            color: #1a2e4a;
            margin: 2rem 0 0.75rem;
            letter-spacing: -0.01em;
        }
        p { margin-bottom: 1rem; color: #6b7280; }
        p strong { color: #1a2e4a; }
        a { color: #e11d48; text-decoration: none; }
        a:hover { color: #c8253a; text-decoration: underline; }
        ul { list-style: none; padding: 0; margin-bottom: 1rem; }
        ul li { padding: 0.3rem 0; color: #6b7280; }
        ul li::before { content: "→ "; color: #e11d48; }
        code {
            font-family: 'JetBrains Mono', monospace;
            font-size: 0.85em;
            background: #f3f4f6;
            padding: 0.15em 0.4em;
            border-radius: 4px;
            color: #1a2e4a;
            border: 1px solid #e5e7eb;
        }
        .snippet-box {
            background: #ffffff;
            border: 1px solid #e5e7eb;
            border-radius: 10px;
            padding: 1.5rem;
            margin: 1rem 0;
            position: relative;
            box-shadow: 0 1px 3px rgba(0,0,0,0.04);
        }
        .snippet-box pre {
            font-family: 'JetBrains Mono', monospace;
            font-size: 0.8rem;
            color: #6b7280;
            white-space: pre-wrap;
            word-break: break-word;
            line-height: 1.5;
            max-height: 400px;
            overflow-y: auto;
        }
        .copy-btn {
            position: absolute;
            top: 0.75rem;
            right: 0.75rem;
            background: #f3f4f6;
            color: #6b7280;
            border: 1px solid #e5e7eb;
            padding: 0.3rem 0.7rem;
            border-radius: 6px;
            font-size: 0.75rem;
            cursor: pointer;
            font-family: 'Inter', sans-serif;
            transition: background 0.15s, color 0.15s;
        }
        .copy-btn:hover { background: #1a2e4a; color: #ffffff; }
        .links { margin-top: 2.5rem; padding-top: 1.5rem; border-top: 1px solid #e5e7eb; }
        .links a { margin-right: 1.5rem; font-size: 0.9rem; }
        footer { margin-top: 3rem; color: #6b7280; font-size: 0.8rem; }
        footer .dot { color: #e11d48; }
        .breadcrumb { margin-bottom: 0.5rem; font-size: 0.85rem; }
        .breadcrumb a { color: #0e7490; }
        .breadcrumb a:hover { color: #1a2e4a; }
    </style>
</head>
<body>
    <main>
        <p class="breadcrumb"><a href="https://twins.la">twins.la</a></p>
        <h1><span class="twilio">twilio</span>.twins.la</h1>
        <p class="tagline">A digital twin of the Twilio SMS and SendGrid Email APIs.</p>

        <h2>What is this?</h2>
        <p>
            This is a high-fidelity digital twin of Twilio's SMS API and SendGrid's Email API.
            Code you write against this twin will work against the real Twilio and SendGrid
            with only hostname and credential changes. No Twilio account needed to develop.
        </p>

        <h2>Supported scenarios</h2>
        <ul>
            <li>Send and receive SMS via the Twilio REST API</li>
            <li>Provision and manage phone numbers</li>
            <li>Webhook delivery with X-Twilio-Signature validation</li>
            <li>Message status progression (queued → sending → sent → delivered)</li>
            <li>TwiML auto-reply parsing</li>
            <li>Send email via SendGrid v3 Mail Send API</li>
            <li>API key authentication for email</li>
        </ul>

        <h2>How to use it</h2>
        <p>
            <strong>Cloud:</strong> Point your app at <code>https://twilio.twins.la</code> instead of
            <code>api.twilio.com</code>. Create an account via
            <code>POST /_twin/accounts</code> and use the returned credentials.
        </p>
        <p>
            <strong>Local:</strong> Install with <code>pip install twins-twilio twins-local</code>
            and run a local instance on any port. Same API, same behavior, your machine.
        </p>

        <h2>For agents</h2>
        <p>
            Copy this into your agent's system prompt, tool configuration, or CLAUDE.md.
            Also available as plain text at
            <a href="/_twin/agent-instructions"><code>/_twin/agent-instructions</code></a>.
        </p>
        <div class="snippet-box">
            <button class="copy-btn" onclick="navigator.clipboard.writeText(document.getElementById('agent-snippet').textContent).then(()=>{this.textContent='Copied!';setTimeout(()=>this.textContent='Copy',1500)})">Copy</button>
            <pre id="agent-snippet">""" + AGENT_INSTRUCTIONS.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;") + """</pre>
        </div>

        <div class="links">
            <a href="https://github.com/twins-la/twilio">GitHub</a>
            <a href="https://twins.la">twins.la</a>
            <a href="/_twin/health">Health</a>
            <a href="/_twin/scenarios">Scenarios</a>
        </div>

        <footer>twins.la <span class="dot">·</span> Where agents meet their environment.</footer>
    </main>
</body>
</html>
"""


@explainer_bp.route("/", methods=["GET"])
def explainer_page():
    """Serve the HTML explainer page."""
    return EXPLAINER_HTML


@explainer_bp.route("/_twin/agent-instructions", methods=["GET"])
def agent_instructions():
    """Serve agent instructions as plain text."""
    return Response(AGENT_INSTRUCTIONS, mimetype="text/plain")
