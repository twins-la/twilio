# Twilio Twin — Supported Scenarios

## SMS (Supported)

The SMS scenario enables sending and receiving SMS messages through a Twilio-compatible REST API. Code written against this twin for the SMS scenario should work against real Twilio with only hostname and credential changes.

### Scope

**In scope:**
- Outbound SMS via `POST /2010-04-01/Accounts/{AccountSid}/Messages.json`
- Inbound SMS via webhook delivery to configured phone number URLs
- Phone number provisioning via IncomingPhoneNumbers API
- Phone number webhook configuration (SmsUrl, SmsMethod)
- Account fetch via Accounts API
- HTTP Basic Auth (AccountSid:AuthToken)
- Twilio-format SIDs (AC, SM, PN prefixes)
- X-Twilio-Signature webhook signing (HMAC-SHA1)
- TwiML `<Message>` response parsing for auto-reply
- Message status progression (queued → sending → sent → delivered)
- StatusCallback delivery for outbound messages
- Message listing and fetching
- Phone number listing, fetching, and updating

**Out of scope (behavior may be fabricated):**
- MMS / media messages
- Voice, video, fax
- Messaging Services
- Subaccounts
- Scheduled messages
- Message redaction / deletion
- Rate limiting
- Billing / usage APIs
- Geographic lookup data (FromCity, FromState, etc. — present but empty)

### Authoritative References

- Twilio Messages API: https://www.twilio.com/docs/messaging/api/message-resource (retrieved 2026-04-04)
- Twilio IncomingPhoneNumber API: https://www.twilio.com/docs/phone-numbers/api/incomingphonenumber-resource (retrieved 2026-04-04)
- Twilio Account API: https://www.twilio.com/docs/iam/api/account (retrieved 2026-04-04)
- Twilio Webhook Security: https://www.twilio.com/docs/usage/security (retrieved 2026-04-04)
- Twilio SMS Webhooks: https://www.twilio.com/docs/messaging/twiml (retrieved 2026-04-04)

### Version

0.1.0 — Initial SMS scenario implementation.
