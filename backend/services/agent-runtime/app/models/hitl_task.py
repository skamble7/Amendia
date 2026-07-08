# app/models/hitl_task.py
# Re-export shim: the contract models now live in the shared amendia_contracts lib
# (Step 2 refactor). This preserves the app.models.hitl_task import path unchanged.
from amendia_contracts.hitl_task import *  # noqa: F401,F403
