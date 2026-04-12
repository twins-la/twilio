"""Twin Plane authentication — re-exports from twins_local.tenants.auth.

The Twin Plane authenticates callers as tenants (HTTP Basic
tenant_id:tenant_secret) or operator admins (Bearer / X-Twin-Admin-Token).
Resource-level auth (Twilio AccountSid:AuthToken) lives in ../auth.py
and governs the Twilio-emulation API surface only.
"""

from twins_local.tenants.auth import (
    require_tenant,
    require_tenant_or_admin,
    require_admin,
)

__all__ = ["require_tenant", "require_tenant_or_admin", "require_admin"]
