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

## Email (Supported)

The Email scenario enables sending email through a SendGrid v3 Mail Send compatible REST API. Code written against this twin for the Email scenario should work against real SendGrid with only hostname and credential changes.

### Scope

**In scope:**
- Outbound email via `POST /v3/mail/send`
- SendGrid-style API key authentication (`Authorization: Bearer SG.xxx`)
- Request body validation (personalizations, from, subject, content)
- 202 Accepted response with `X-Message-Id` header
- SendGrid-format error responses (`{"errors": [...]}`)
- Email storage and retrieval via Twin Plane
- Email delivery status simulation (processed → delivered)
- API key creation via Twin Plane
- Operation logging for all email operations

**Out of scope (behavior may be fabricated):**
- Inbound email / Inbound Parse
- Event webhooks (delivery, open, click notifications)
- SendGrid Marketing API (contacts, lists, segments)
- SendGrid Template Engine / dynamic templates (template_id is accepted but not rendered)
- SendGrid Statistics / Analytics API
- SendGrid Suppressions (bounces, blocks, spam reports)
- Attachments (accepted in request body but not processed)
- Mail settings (sandbox_mode, footer, etc. — accepted but not applied)
- Tracking settings (click, open tracking — accepted but not applied)
- Scheduled sends (send_at accepted but not delayed)
- Rate limiting
- SMTP relay

### Authoritative References

- SendGrid Mail Send API: https://www.twilio.com/docs/sendgrid/api-reference/mail-send/mail-send (retrieved 2026-04-06)
- SendGrid Authentication: https://www.twilio.com/docs/sendgrid/for-developers/sending-email/authentication (retrieved 2026-04-06)
- SendGrid X-Message-Id: https://www.twilio.com/docs/sendgrid/glossary/x-message-id (retrieved 2026-04-06)
- SendGrid Error Format: https://www.twilio.com/docs/sendgrid/api-reference/how-to-use-the-sendgrid-v3-api/responses (retrieved 2026-04-06)

### Version

0.2.0 — Email scenario added.
