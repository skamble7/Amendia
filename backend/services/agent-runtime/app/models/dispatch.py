# app/models/dispatch.py
# Re-export shim: the contract models now live in the shared amendia_contracts lib
# (Step 2 refactor). This preserves the app.models.dispatch import path unchanged.
from amendia_contracts.dispatch import *  # noqa: F401,F403
