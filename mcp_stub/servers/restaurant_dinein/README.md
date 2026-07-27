# restaurant_dinein MCP server

The domain-simple **"hello world"** twin of `wire_transfer_exception` — the same shape, a friendlier
domain. It proves Amendia's domain-neutrality: the platform image gains **zero** restaurant code; the
`restaurant-dinein` process runs as onboarded data (BPMN + manifest) plus this external MCP server,
exactly like the re-homed wire pack (ADR-047 D2).

Streamable-HTTP MCP at `/mcp` + a `/health` route. Network alias `dinein-mcp`, port **8070**.
Deterministic, dumb handlers (pure functions of their input — no clock, no randomness, no network) so
the same call always yields the same output, including `action_id`. An import-time compliance
self-check (`check_compliance`) refuses to start a non-compliant server.

## Tools (6) — all Amendia-MCP-compliant

Read-only:
1. `get_menu` → `{sections:[{name, items:[{name, price, available, tags[]}]}], currency}`
2. `validate_order` → `{order_verdict: "ok"|"needs_info" (required), issues[], unavailable_items[]}`
3. `screen_allergens` → `{allergen_status: "clear"|"conflict" (required), conflicts[], matched_allergens[]}`
4. `generate_bill` → `{line_items[], subtotal, tax, total (required), currency}`

Side-effectful (guideline acknowledgement `acknowledged` + `action_id` + `status`):
5. `fire_ticket` → ack + `ticket_ref`, `fired_at`
6. `charge_payment` → ack + `payment_status: "captured"|"declined" (required)`, `payment_ref`, `amount`, `charged_at`

## Demo steering (deterministic branch control)

- `validate_order` → `needs_info` (revise loop) when a requested item is 86'd (name contains `86` or
  `available: false`), or `hint` ∈ {`needs_info`, `unavailable`, `revise`}; else `ok` (`hint: "ok"` forces clean).
- `screen_allergens` → `conflict` (revise loop) when an ordered item's `tags` intersect the party's
  `dietary_flags`, or `hint: "conflict"`; else `clear` (`hint: "clear"` forces clear).
- `charge_payment` → `declined` (payment-resolution loop) when `tender: "declined"` or `amount` > 500;
  else `captured`. A declined charge moves **no** money (`acknowledged: false`, `status: "rejected"`).
- `action_id` = `hash(tool + ticket_id)` → idempotent, auditable, deterministic.

## Run locally

```bash
pip install -e '.[test]'
python -m pytest -q            # 25 contract + behaviour tests
restaurant-dinein-mcp          # serves on :8070  (GET /health, POST /mcp)
```

## Compose wiring (for reference — not applied here)

Add a service alias `dinein-mcp` on port 8070 mirroring `wirefix-mcp`, and the pack's capability
descriptors point at `http://dinein-mcp:8070/mcp`.
