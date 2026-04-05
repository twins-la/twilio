"""TwiML response parser.

Parses the XML response from a webhook to extract reply messages.
Only supports the <Message> verb for 0.1.0 (SMS scenario).
"""

import logging
import xml.etree.ElementTree as ET

logger = logging.getLogger(__name__)


def parse_message_response(twiml_text: str) -> list[str]:
    """Parse a TwiML response and extract message bodies.

    Supports both forms:
        <Response><Message>Hello</Message></Response>
        <Response><Message><Body>Hello</Body></Message></Response>

    Returns:
        List of message body strings found in the TwiML.
    """
    messages = []
    try:
        root = ET.fromstring(twiml_text.strip())
        if root.tag != "Response":
            logger.warning("TwiML root element is '%s', expected 'Response'", root.tag)
            return messages

        for msg_elem in root.findall("Message"):
            # Check for <Body> subelement first
            body_elem = msg_elem.find("Body")
            if body_elem is not None and body_elem.text:
                messages.append(body_elem.text)
            elif msg_elem.text and msg_elem.text.strip():
                # Direct text content in <Message>
                messages.append(msg_elem.text.strip())

    except ET.ParseError:
        logger.warning("Failed to parse TwiML response: %s", twiml_text[:200])

    return messages
