# app/models/artifact_schema.py
# Re-export shim: the contract models now live in the shared amendia_contracts lib
# (Step 2 refactor). This preserves the app.models.artifact_schema import path unchanged.
from amendia_contracts.artifact_schema import *  # noqa: F401,F403
