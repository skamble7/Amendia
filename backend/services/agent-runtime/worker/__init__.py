"""The Amendia capability-worker (ADR-020).

A plain RabbitMQ consumer that runs the shared execution core (`app.engine.executor.core`)
for one capability per job and publishes the correlated result. It carries no Mongo /
checkpoint / HITL responsibility — the host owns all of that; the worker returns raw outputs.

Runs as an ordinary process in dev/CI (no OpenShell needed). In production it is launched
*inside* an OpenShell sandbox via `nemoclaw onboard`, reaching out to RabbitMQ,
`inference.local/v1`, and MCP servers under the sandbox's creation-time egress allowlist.
"""
