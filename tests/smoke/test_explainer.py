"""Smoke tests for the explainer page and agent instructions."""

from twins_local.testing import assert_no_html_entity_in_css_content


def test_explainer_has_no_html_entities_inside_css_content(client):
    """Sweep-style class check (Job 022): catches the entity-in-CSS-content
    bug class that shipped in Job 020 / fixed in Job 021 for telegram. Now
    enforced sibling-wide via twins_local.testing.
    """
    assert_no_html_entity_in_css_content(client.get("/").get_data(as_text=True))


class TestExplainerPage:
    """Test the root explainer page."""

    def test_root_returns_html(self, client):
        resp = client.get("/")
        assert resp.status_code == 200
        assert b"twilio.twins.la" in resp.data
        assert b"text/html" in resp.content_type.encode()

    def test_root_contains_agent_snippet(self, client):
        resp = client.get("/")
        assert b"agent-snippet" in resp.data
        assert b"copy-btn" in resp.data

    def test_root_contains_human_sections(self, client):
        resp = client.get("/")
        assert b"What is this?" in resp.data
        assert b"Supported scenarios" in resp.data
        assert b"How to use it" in resp.data


class TestAgentInstructions:
    """Test the agent instructions endpoint."""

    def test_returns_plain_text(self, client):
        resp = client.get("/_twin/agent-instructions")
        assert resp.status_code == 200
        assert "text/plain" in resp.content_type

    def test_contains_required_sections(self, client):
        text = client.get("/_twin/agent-instructions").data.decode()
        assert "Authentication" in text
        assert "Key Endpoints" in text
        assert "Quick Start" in text
        assert "Local Usage" in text
        assert "Feedback" in text
        assert "Reference" in text

    def test_is_self_contained(self, client):
        text = client.get("/_twin/agent-instructions").data.decode()
        # Must contain actual endpoint paths
        assert "/2010-04-01/Accounts/" in text
        assert "/v3/mail/send" in text
        assert "/_twin/accounts" in text
        assert "/_twin/feedback" in text
        # Must contain auth info
        assert "Basic Auth" in text
        assert "Bearer" in text
