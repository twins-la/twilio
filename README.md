# Twilio Twin

A digital twin of the Twilio SMS API for [twins.la](https://twins.la).

## What This Is

A Python package that emulates Twilio's SMS REST API with high fidelity. Existing Twilio SDK code can be pointed at this twin by changing only the hostname and credentials. The twin simulates message delivery internally — no real SMS provider needed.

## Supported Scenarios

See [SCENARIOS.md](SCENARIOS.md) for the full scope and authoritative references.

- **SMS** — Send and receive SMS via Twilio-compatible REST API, including webhook delivery with X-Twilio-Signature signing.

## Usage

This package is not run directly. It is loaded by a host:

- **Local**: `twins-twilio-local` (sibling package under `twins_twilio_local/`) — run locally via gunicorn or `python -m twins_twilio_local`
- **Cloud**: available at [twilio.twins.la](https://twilio.twins.la)

## Quick Start (local)

```bash
pip install -e . ./twins_twilio_local/
python -m twins_twilio_local
```

Then use the Twilio Python SDK:

```python
from twilio.rest import Client

# Create an account via Twin Plane
import requests
resp = requests.post("http://localhost:8080/_twin/accounts", json={"friendly_name": "Dev"})
account = resp.json()

# Use the Twilio SDK
client = Client(account["sid"], account["auth_token"])
client.api.base_url = "http://localhost:8080"

# Provision a number
number = client.incoming_phone_numbers.create(phone_number="+15551234567")

# Send a message
message = client.messages.create(
    to="+15559876543",
    from_="+15551234567",
    body="Hello from the twin!"
)
```

