# Restaurant Dine-In — Wizard Onboarding Kit ("Hello World" for Amendia)

**What this is.** A deliberately *domain-simple* second process — a party is seated, orders, is served,
and pays — that exercises the **same control spine** as the wire-transfer reference. It lets a newcomer
focus on understanding Amendia (gates, artifacts, capabilities, loops) instead of the domain. And it
proves **domain-neutrality**: the platform image gains **zero** restaurant code. The process runs as
onboarded data (this BPMN + the configuration below) plus one external MCP server — exactly like the
re-homed wire pack (ADR-047 D2).

**This kit onboards via the wizard — it is *not* seeded.** Nothing here is added to
`backend/services/agent-runtime/seed/` and nothing is auto-loaded. You import the BPMN, point the wizard
at the running MCP server, author the few non-introspectable artifacts, and set the bindings below.

**Files in this kit**
- `dine-in.bpmn` — the executable process to import.
- `schemas/art.dining.order_ticket.json` — the **trigger** schema (author in the wizard).
- `schemas/art.dining.order.json` — the human/agent **order** artifact (author in the wizard).
- `schemas/art.dining.payment_retry.json` — the human **retry** artifact (author in the wizard).
- `capabilities/cap.dining.draft_order.json` — the **llm** assist capability (author in the wizard).
- `sample/order-ticket-sample.json` — a sample trigger to kick off a run.
- The MCP server lives at `mcp_stub/servers/restaurant_dinein/` (alias `dinein-mcp`, port `8070`).

---

## 1. Prerequisites

1. **Run the MCP server.** Build/run `mcp_stub/servers/restaurant_dinein/` (or add it to compose with
   network alias `dinein-mcp`, port `8070`). Health-check: `GET http://dinein-mcp:8070/health` → `{"status":"ok","tools":6}`.
2. **Introspect it in the wizard.** Point the capability step at `http://dinein-mcp:8070/mcp`. The wizard
   generates the **six** `mcp` capabilities and their input/output artifact schemas:

   | Tool | Capability (generated) | side_effect | Output artifact (used as) |
   |---|---|---|---|
   | `get_menu` | `cap.dining.get_menu` | read_only | `menu` |
   | `validate_order` | `cap.dining.validate_order` | read_only | `validation` |
   | `screen_allergens` | `cap.dining.screen_allergens` | read_only | `allergen` |
   | `generate_bill` | `cap.dining.generate_bill` | read_only | `bill` |
   | `fire_ticket` | `cap.dining.fire_ticket` | **side_effectful** | — (acknowledgement) |
   | `charge_payment` | `cap.dining.charge_payment` | **side_effectful** | `receipt` |

3. **Author the four non-introspectable pieces** (they are not tool outputs, so introspection can't see
   them) using the JSON in this kit: the trigger `art.dining.order_ticket`, the `art.dining.order`, the
   `art.dining.payment_retry`, and the `llm` capability `cap.dining.draft_order`.

   `art.dining.order` and `art.dining.payment_retry` are **operator-authored artifacts (ADR-050)** — neither
   a tool's I/O nor the trigger, but the shapes **human** tasks produce. Declare each with the wizard's
   **"author an artifact schema"** affordance (the same panel that declares the trigger, generalized): paste
   the `json_schema` from `schemas/art.dining.order.json` / `schemas/art.dining.payment_retry.json`. Once
   declared, a human binding's **Outputs** section can produce them (Step 2 below), and every downstream
   capability input can be **sourced from that human output** — `art.dining.order` is where the whole `order`
   data-flow originates (not the trigger).

> **The one rule that makes the pack valid:** a gateway may only branch on a **`required`,
> upstream-produced field**, and the binding **output name** is what the FEEL condition reads. So the
> Validate-order binding's output **must be named `validation`**, Allergen-screen's **`allergen`**, and
> Process-payment's **`receipt`** — matching the BPMN conditions
> `validation.order_verdict = "ok"`, `allergen.allergen_status = "clear"`, `receipt.payment_status = "captured"`.
>
> **You don't type these by hand (ADR-051).** The wizard **auto-names** a capability's output from the gateway
> it feeds: because `Task_ValidateOrder` flows into `Gateway_OrderOK` (condition `validation.order_verdict`),
> its output defaults to **`validation`** — likewise **`allergen`** (`Task_ScreenAllergens` → `Gateway_AllergenClear`)
> and **`receipt`** (`Task_ProcessPayment` → `Gateway_PaymentOK`). Each Bindings row shows an editable **Output
> name** field with a "from gateway" chip; leave it as-is so the gateways branch. (Absent this, introspection
> would name them `validate_order_output` / … , which no condition matches — a silently non-branching gateway,
> now caught at Review with `gateway_condition_unproduced`.)

---

## 2. Bindings — what to set for each BPMN element

Roles used: **`role.dining.server`** (waitstaff), **`role.dining.kitchen`** (chef/expo),
**`role.dining.manager`**. HITL modes touch all five: `none`, `review_after`, `approve_result`,
`approve_actions`, `manual`.

| # | Element | Executor | HITL | Role | Inputs | Outputs |
|---|---|---|---|---|---|---|
| 1 | `Task_PresentMenu` | `cap.dining.get_menu` | none | — | `trigger` | `menu` |
| 2 | `Task_TakeOrder` | **human**, assist `cap.dining.draft_order` | manual | server | `menu` | `order` |
| 3 | `Task_ValidateOrder` | `cap.dining.validate_order` | review_after | server | `order` | `validation` |
| 4 | `Task_ReviseOrder` | **human** | manual | server | `order`, `validation` | `order` |
| 5 | `Task_ScreenAllergens` | `cap.dining.screen_allergens` | **approve_result** | kitchen | `order` | `allergen` |
| 6 | `Task_FireTicket` | `cap.dining.fire_ticket` | **approve_actions** | kitchen | `order`, `allergen` | — |
| 7 | `Task_PrepareReady` | **human** | manual | kitchen | `order` | — |
| 8 | `Task_ServiceRecovery` | **human** | manual | manager | `order` | — |
| 9 | `Task_ServeOrder` | **human** | manual | server | `order` | — |
| 10 | `Task_GenerateBill` | `cap.dining.generate_bill` | none | — | `order` | `bill` |
| 11 | `Task_ProcessPayment` | `cap.dining.charge_payment` | **approve_actions** | manager | `bill` | `receipt` |
| 12 | `Task_ResolvePayment` | **human** | manual | server | `receipt` | `payment_retry` |

`Task_FireTicket` and `Task_ProcessPayment` are side-effectful → the platform **forces** `≥ approve_actions`
(the wizard will not let you weaken them). Everything else is your choice; the modes above give the full tour.

**Human outputs are first-class (ADR-050).** The `Outputs` column above is not decoration — for a capability
task it is mirrored from the tool, but for a **human** task **you declare it**. In each human binding's
**Outputs** section, add the output and point it at the authored artifact schema you declared in Step 1.3:
- `Task_TakeOrder` → output **`order`** = `art.dining.order` (its `assist_capability` `cap.dining.draft_order`
  pre-drafts; the server confirms/edits).
- `Task_ReviseOrder` → output **`order`** = `art.dining.order` (the loop re-produces the same artifact).
- `Task_ResolvePayment` → output **`payment_retry`** = `art.dining.payment_retry`.

These declared outputs are what make `order` and `payment_retry` **selectable upstream sources** for the
capability inputs below — a from-artifact source resolving to a human-authored artifact, not the trigger.

### 2a. Input maps (the composite field mappings)

Most bindings read a single named artifact and need no map. Four bindings compose fields from the trigger
and other artifacts — enter these exactly (same shape as the wire manifest). **Where `{from: artifact, name:
"order"}` appears below, it resolves to `Task_TakeOrder`'s (or, after a revise, `Task_ReviseOrder`'s) declared
human output (ADR-050) — the wizard's source picker offers it as `order (Task_TakeOrder)`, and it pre-fills for
you once those human outputs are declared.** So `Task_ValidateOrder`, `Task_ScreenAllergens`,
`Task_GenerateBill`, and `Task_FireTicket` all read the **human-authored** `order`, not the trigger:

`Task_PresentMenu` (`get_menu`):
```json
{ "trigger": { "fields": {
  "request":    { "from": "trigger" },
  "ticket_id":  { "from": "trigger", "path": "ticket_id" }
}}}
```

`Task_ValidateOrder` (`validate_order`) and `Task_GenerateBill` (`generate_bill`):
```json
{ "order": { "fields": {
  "order":     { "from": "artifact", "name": "order" },
  "ticket_id": { "from": "trigger",  "path": "ticket_id" }
}}}
```

`Task_ScreenAllergens` (`screen_allergens`):
```json
{ "order": { "fields": {
  "order":     { "from": "artifact", "name": "order" },
  "party":     { "from": "trigger",  "path": "" },
  "ticket_id": { "from": "trigger",  "path": "ticket_id" }
}}}
```
(The party's `dietary_flags` ride inside the trigger; the tool reads `party.dietary_flags`.)

`Task_ProcessPayment` (`charge_payment`) — this is the loop-safety wiring:
```json
{ "bill": { "fields": {
  "ticket_id":   { "from": "trigger",  "path": "ticket_id" },
  "amount":      { "from": "artifact", "name": "bill", "path": "total" },
  "tender":      { "from": "artifact", "name": "payment_retry", "path": "tender", "optional": true },
  "tender_hint": { "from": "trigger",  "path": "tender",  "optional": true }
}}}
```
Here `{from: artifact, name: "payment_retry"}` resolves to **`Task_ResolvePayment`'s declared human output**
(ADR-050) — the source picker offers it as `payment_retry (Task_ResolvePayment)`. On the first pass there is no
`payment_retry`, so the trigger's `tender` (the `tender_hint`) decides. On a retry, the human's
`payment_retry.tender` takes precedence — a non-`declined` tender **captures and ends the loop**. This is the
same human-authored-precedence pattern that fixes the wire needs-info loop; it is why the resolve loop can never
spin forever.

---

## 3. Gateways, separation of duties, triage

**Gateway variables** (each must be a `required` field of the named output artifact):

| Gateway | Variable | Source artifact | Branches |
|---|---|---|---|
| `Gateway_OrderOK` | `validation.order_verdict` | `art.dining.order_validation` | `ok` → screen; **default** `needs_info` → revise |
| `Gateway_AllergenClear` | `allergen.allergen_status` | `art.dining.allergen_result` | `clear` → fire; **default** `conflict` → revise |
| `Gateway_PaymentOK` | `receipt.payment_status` | `art.dining.payment_receipt` | `captured` → end; **default** `declined` → resolve |

**In the wizard (Policies step).** Each gateway pre-fills its **Decision variable** from the BPMN condition —
`validation.order_verdict`, `allergen.allergen_status`, `receipt.payment_status`. The variable's **first
segment lines up with the output name you set in Bindings** (`validation` / `allergen` / `receipt`, ADR-051):
that alignment is exactly what lets the gateway resolve (the variable's first segment IS the produced output
name). You only add the **Source artifact** — the output artifact of the capability feeding the gateway
(`art.dining.order_validation` / `art.dining.allergen_result` / `art.dining.payment_receipt`), whose
`required` field the branch reads. If you renamed a capability's output in Bindings, use the same name here.

**Separation of duties (`distinct_actor`)** — the person who authored the order must not be the person who
authorizes the two irreversible actions:
- `{ Task_TakeOrder, Task_FireTicket }`
- `{ Task_TakeOrder, Task_ProcessPayment }`

(These are naturally satisfied by the server/kitchen/manager role split, and the platform also enforces
them per-instance from who actually acted.)

**Declare the trigger schema first (ADR-049).** In the wizard's **Triage** step, open the **Trigger schema**
panel and declare the pack's trigger: set the artifact id to `art.dining.order_ticket` and paste the
`json_schema` from `schemas/art.dining.order_ticket.json`. The wizard registers it, emits it as the pack's
`ProcessPack.trigger`, and flattens it into the field picker — so the rule below authors against the **declared
dining fields** (`order_type`, `dietary_flags`, `party_size`, `requested_items`, `seated_at`, `table`, `tender`,
`ticket_id`), with **no** dependency on any `SEED_DIR/sample-exception`. (Skip the declaration and the picker
falls back to the deployment's sample envelopes; the dine-in pack ships none, so declaring is the path.)

**Triage rule** — with the trigger declared, pick `order_type` from the field picker and author the rule that
claims only dine-in tickets, so it never collides with the wire packs:
```json
{ "rule_id": "dine-in", "priority": 200,
  "when": { "all": [ { "field": "order_type", "op": "eq", "value": "dine_in" } ] } }
```
Trigger artifact (declared + emitted as `ProcessPack.trigger`): `art.dining.order_ticket@^1.0.0`.

---

## 4. Driving each branch (a deterministic demo)

The MCP handlers are dumb and deterministic, with small steering hints so you can walk every path:

- **Happy path** — use `sample/order-ticket-sample.json` but drop the 86'd item: order Margherita Pizza +
  Grilled Salmon + Sorbet, dietary_flags `["nuts"]` (none of those carry nuts). Validate → `ok`; allergens
  → `clear`; fire (approve); prepare/serve; bill; pay → `captured`; **Served & paid**.
- **Order revise loop** — put an 86'd item on the order (the menu's "Lobster Thermidor (86)", or any line
  whose name contains `86` / `available:false`). Validate → `needs_info` → **Revise order** → remove it →
  re-validate → `ok`.
- **Allergen revise loop** — with dietary_flags `["nuts"]`, order the "Peanut Parfait" (tags include
  `nuts`). Screen → `conflict` → **Revise order** → swap the dessert → re-screen → `clear`.
- **SLA breach** — leave `Task_PrepareReady` unclaimed past its **PT30M** timer; the interrupting boundary
  fires **Service recovery** (manager), which rejoins at **Serve order**. (Shorten `PT30M` in the BPMN for
  a quick demo.)
- **Payment decline loop** — set `"tender":"declined"` on the trigger. First charge → `declined` →
  **Resolve payment** (server picks `tender:"card"`) → re-charge → `captured`. Terminates by construction.

---

## 5. Feature coverage (why this is "complex enough")

One small process touches the major surfaces of Amendia:

- **Capability kinds:** `mcp` read-only (get_menu, validate_order, screen_allergens, generate_bill),
  `mcp` side-effectful (fire_ticket, charge_payment), and `llm` (draft_order assist).
- **All five HITL modes:** none, review_after, approve_result, approve_actions, manual.
- **Three exclusive gateways**, each branching on a `required`, upstream-produced field.
- **Two rework loops** — order-revise (two inbound joins) and payment-resolve — both terminating by
  human-authored precedence, not by luck.
- **An interrupting SLA timer boundary** (on the non-side-effect Prepare task — the platform forbids a
  timer on a side-effect task) with an escalation path.
- **Four-eyes / separation of duties** on the two irreversible actions.
- **Side-effect acknowledgement** (`acknowledged` + `action_id` + `status`) behind forced `approve_actions`
  gates, with the human approval tied to the `action_id`.
- **An array-of-objects artifact** (`order.lines[]`) exercising the repeatable schema-form.
- **Convergent joins** (Serve order and Validate order each take two inbound flows).

## 6. Optional "Level 2" extensions (each adds one advanced feature)

If you later want to push coverage further, these map cleanly onto the same story and mirror existing wire
variants: a **decision (DMN)** step routing high-value/alcohol orders to a manager gate (`wire-repair-dmn`);
a **deep_agent** "menu sommelier" that investigates dietary needs via a bounded tool loop
(`wire-repair-agentic`, nemoclaw); a **reduce** collapsing per-line allergen checks into one "any conflict?"
summary (`wire-repair-screening`); a **call_activity** to a shared payment sub-process (`compose-caller`);
and **compensation** to void a fired ticket if payment ultimately fails (`payment-compensation`). The
current design deliberately uses gateways (not error boundaries) for the 86'd/declined cases so it runs
cleanly on the first onboarding; error-boundary variants are a natural next step.
