# LEGACY ROUTING MATRIX - DEPRECATED
# This file is retained for backward compatibility only.
# All routing logic has been moved to backend/app/tool_selector.py.

# DO NOT ADD NEW ROUTING LOGIC HERE.
# Empty constants to prevent immediate crashes if any hidden imports exist.

ROUTING_MATRIX = {}
DOMAIN_REQUIRED_TOOLS = {}

def contextual_route(*args, **kwargs):
    """Deprecated: Use tool_selector.select_tools instead."""
    return {"required": [], "optional": [], "forbidden": []}
