# Wire Transfer Exception Reference — the Amendia POC Scenario

This document defines the first exception Amendia handles end to end: what a wire exception is in practice, the industry standards that shape its representation, the normalized payload the dummy generator will emit (ADR-006 D2), the handling process a bank typically runs, and its BPMN 2.0 implementation (the `wire-repair-standard` ProcessPack).

## 1. Wire transfer exceptions in practice

A wire (high-value credit transfer) becomes an exception when it cannot complete straight-through processing (STP). The common families a payments ops team sees:

- **Repair / unable-to-apply** — the beneficiary bank (or an intermediary) cannot apply the funds: invalid or closed beneficiary account, misspelled name, missing address, wrong or unreachable BIC/routing number. Funds sit in suspense while ops investigates.
- **Returns** — the payment is sent back, with a reason code, because it could not be applied or was refused.
- **Compliance holds** — sanctions/AML screening hits pause the payment pending review (handled by compliance, usually a separate process).
- **Recalls / cancellations** — the originator asks for the payment back (fraud, duplicate, wrong amount).
- **Claims of non-receipt / cover mismatches** — the beneficiary says funds never arrived, or the announcement (MT103/pacs.008) and the cover settlement disagree.

The POC targets the first family — **unable-to-apply → repair or return** — because it is the highest-volume investigative workload, exercises every platform feature (investigation, judgment verdict, four-eyes approval, side-effectful release, return branch), and is well covered by standards.

## 2. Standards landscape

**ISO 20022** is the current lingua franca (SWIFT cross-border MT→MX migration for the interbank space):

- `pacs.008` — FI-to-FI customer credit transfer: the wire itself. Key identifiers: **UETR** (unique end-to-end transaction reference, a UUID carried across the whole chain and used by SWIFT gpi tracking), instruction id, end-to-end id.
- `pacs.004` — payment return, carrying a structured return reason.
- **Exceptions & Investigations (E&I) messages**: `camt.026` *Unable To Apply* (the case-opening message for exactly our scenario), `camt.027` claim non-receipt, `camt.087` request to modify payment, `camt.056` cancellation request, `camt.029` resolution of investigation (the case-closing answer).
- **External code sets** — ISO-maintained reason codes reused across these messages. Representative codes for our scenario: `AC01` incorrect account number, `AC04` closed account, `AC06` blocked account, `RC01` bank identifier incorrect, `BE04` missing creditor address, `AM09` wrong amount, `AGNT` incorrect agent, `NARR` narrative (free-text reason).

**Legacy SWIFT MT** still appears from real systems: `MT103` (the wire), `MT199`/`MT299` free-format investigation messages, and the `MTn95/n96` query/answer pairs. **SWIFT gpi** contributes the UETR-based tracker that ops uses to locate where funds are stuck. Domestic rails (Fedwire, CHIPS, TARGET2) have their own formats but map to the same semantics; Fedwire has itself migrated to ISO 20022.

**Design consequence for Amendia:** the normalized exception envelope is *ISO 20022-aligned rather than ISO 20022-verbatim* — camt.026-shaped semantics with external-code-set reason codes and a pacs.008-shaped payment block, flattened into pragmatic JSON. This keeps triage rules and the future knowledge graph on standard vocabulary while sparing the POC full ISO XML processing. A real connector later maps camt.026/MT199 into this envelope.

## 3. The POC scenario

An outbound USD 250,000 customer wire (pacs.008) from Bank Alpha is reported unable-to-apply by the beneficiary bank: the account number does not exist (`AC01`), and the ops screenshot suggests a digit transposition against the name-matched account. Ops must investigate, decide repairability, repair-and-release with four-eyes approval (re-screening sanctions after any change to beneficiary data), request missing information if inconclusive, or return the funds (pacs.004) if unrepairable.

## 4. Normalized exception envelope (what the generator emits; conforms to `pin.payments.wire_exception`)

```json
{
  "exception_id": "EXC-2026-000123",
  "source": { "system": "payment-hub-sim", "channel": "swift" },
  "received_at": "2026-07-06T09:14:03Z",
  "exception_type": "unable_to_apply",
  "reason_codes": ["AC01"],
  "reason_narrative": "Beneficiary account not found at beneficiary bank; possible digit transposition per attached screenshot.",
  "status": "open",
  "payment": {
    "msg_type": "pacs.008.001.10",
    "uetr": "eb6305c9-1f7f-49de-aefa-19d2ba8f11f4",
    "instruction_id": "BKALPHA20260705INS0042",
    "end_to_end_id": "INV-88231-PAY",
    "settlement_amount": { "currency": "USD", "value": 250000.00 },
    "value_date": "2026-07-05",
    "debtor": { "name": "Northline Industrial Supply LLC" },
    "debtor_agent": { "bic": "ALPHUS33" },
    "creditor": { "name": "Kestrel Components GmbH", "account": { "id": "DE44500105175407324931", "scheme": "IBAN" } },
    "creditor_agent": { "bic": "KSTLDEFF" },
    "charges": "SHA"
  },
  "related_messages": [
    { "type": "camt.026", "id": "CASE-KSTL-77812", "assigner_bic": "KSTLDEFF" }
  ],
  "attachments": [
    { "attachment_id": "att-1", "name": "beneficiary-screen.png", "media_type": "image/png",
      "sha256": "9f2b64…", "fetch_url": "https://exception-store/exceptions/EXC-2026-000123/attachments/att-1" },
    { "attachment_id": "att-2", "name": "analyst-notes.txt", "media_type": "text/plain",
      "sha256": "c11a02…", "fetch_url": "https://exception-store/exceptions/EXC-2026-000123/attachments/att-2" }
  ]
}
```

Triage mapping rule that catches it (ADR-006 D3): `exception_type = "unable_to_apply" AND payment.msg_type starts with "pacs.008" AND reason_codes ∩ {AC01, AC04, RC01, BE04} ≠ ∅ → pack key wire-repair-standard`.

## 5. The handling process as banks typically run it

L1 payment-ops receives the case, pulls the payment record, gpi/tracker status, account history, and any correspondence, and assembles the picture (**enrich & investigate**). An experienced analyst then judges **repairability**: is there enough evidence (name match, prior payments to a similar account, attached correspondence) to correct the beneficiary details with confidence? Three outcomes are standard: *repairable* → draft the corrected instruction; *needs information* → go back to the originator or beneficiary bank (camt.027/MT199-style request) and re-assess when answers arrive; *unrepairable* (or recall demanded, or funds must not be applied) → draft a return (pacs.004 with reason). Any repair to beneficiary data triggers a **sanctions re-screen** before release — the corrected party may hit a list the original did not. Repairs and returns are executed only after **four-eyes approval** by a second, more senior operator (approver ≠ proposer — the separation-of-duties constraint from our actor model). After release or return, the bank **notifies parties** (originator advice, camt.029 to close the investigation case) and **records the resolution** for audit and MIS. Typical roles: `role.payments.ops_analyst` (investigate, obtain info), `role.payments.ops_approver` (four-eyes), with compliance implicit in the re-screen capability.

## 6. BPMN model → Amendia annotations

Element subset check: start/end events, service tasks, user tasks, one exclusive gateway — fully inside the ADR-001 §6.6 Iteration-1 subset. (The post-repair notify/record steps run **sequentially**, not in parallel — see §8; the agent-runtime plan compiler in Step 3 does not support parallel gateways yet.) Manifest bindings (sidecar per ADR-002 D1; the XML stays annotation-free):

| BPMN element | Kind | Capability / role | HITL |
|---|---|---|---|
| Task_EnrichPayment | service | cap.payment.enrich_investigation (agent) | none |
| Task_AssessRepairability | service | cap.payment.assess_beneficiary (agent) → writes `beneficiary.repair_verdict` | review_after |
| Gateway_Repairable | exclusive | FEEL on `beneficiary.repair_verdict` | — |
| Task_ObtainInfo | user | role.payments.ops_analyst (agent pre-drafts the RFI) | manual |
| Task_DraftRepair | service | cap.payment.draft_repair (agent) | review_after |
| Task_ApproveRepair | user | role.payments.ops_approver (four-eyes; approver ≠ Task_DraftRepair actor) | manual |
| Task_SanctionsRescreen | service | cap.payment.sanctions_screen (mcp) | approve_result |
| Task_ApplyRepair | service | cap.payment.apply_repair (agent) | approve_actions |
| Task_NotifyParties | service | cap.payment.notify_parties (agent; drafts camt.029/advices) | approve_actions |
| Task_RecordResolution | service | cap.payment.record_resolution (llm) | none |
| Task_DraftReturn | service | cap.payment.draft_return (agent; pacs.004 + reason) | review_after |
| Task_ApproveReturn | user | role.payments.ops_approver | manual |
| Task_ExecuteReturn | service | cap.payment.execute_return (agent) | approve_actions |

## 7. BPMN 2.0 XML (`wire-repair.bpmn`)

```xml
<?xml version="1.0" encoding="UTF-8"?>
<bpmn:definitions xmlns:bpmn="http://www.omg.org/spec/BPMN/20100524/MODEL"
                  xmlns:bpmndi="http://www.omg.org/spec/BPMN/20100524/DI"
                  xmlns:dc="http://www.omg.org/spec/DD/20100524/DC"
                  xmlns:di="http://www.omg.org/spec/DD/20100524/DI"
                  xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance"
                  id="Definitions_WireRepair"
                  targetNamespace="http://amendia.example/processes/wire-repair"
                  exporter="Amendia" exporterVersion="0.1">
  <bpmn:process id="Process_WireRepairStandard"
                name="Wire Transfer Exception - Unable to Apply / Repair"
                isExecutable="true">
    <bpmn:documentation>Handles unable-to-apply wire exceptions (camt.026 semantics): investigate,
    assess repairability, repair-and-release with four-eyes approval and sanctions re-screen,
    request missing information, or return funds (pacs.004). Execution metadata lives in the
    Amendia annotation manifest (ADR-002), not in this file. Post-repair notification and
    resolution-recording run sequentially (the Iteration-1 executable subset excludes parallel
    gateways; see wire-transfer-exception-reference.md §6/§8).</bpmn:documentation>

    <bpmn:startEvent id="Start_ExceptionReceived" name="Wire exception received">
      <bpmn:outgoing>Flow_Start_Enrich</bpmn:outgoing>
    </bpmn:startEvent>

    <bpmn:serviceTask id="Task_EnrichPayment" name="Enrich &amp; investigate payment">
      <bpmn:incoming>Flow_Start_Enrich</bpmn:incoming>
      <bpmn:outgoing>Flow_Enrich_Assess</bpmn:outgoing>
    </bpmn:serviceTask>

    <bpmn:serviceTask id="Task_AssessRepairability" name="Assess repairability">
      <bpmn:incoming>Flow_Enrich_Assess</bpmn:incoming>
      <bpmn:incoming>Flow_Info_Assess</bpmn:incoming>
      <bpmn:outgoing>Flow_Assess_Gateway</bpmn:outgoing>
    </bpmn:serviceTask>

    <bpmn:exclusiveGateway id="Gateway_Repairable" name="Repairable?" default="Flow_NeedsInfo">
      <bpmn:incoming>Flow_Assess_Gateway</bpmn:incoming>
      <bpmn:outgoing>Flow_Repairable</bpmn:outgoing>
      <bpmn:outgoing>Flow_Unrepairable</bpmn:outgoing>
      <bpmn:outgoing>Flow_NeedsInfo</bpmn:outgoing>
    </bpmn:exclusiveGateway>

    <bpmn:userTask id="Task_ObtainInfo" name="Obtain missing information">
      <bpmn:incoming>Flow_NeedsInfo</bpmn:incoming>
      <bpmn:outgoing>Flow_Info_Assess</bpmn:outgoing>
    </bpmn:userTask>

    <bpmn:serviceTask id="Task_DraftRepair" name="Draft repair instruction">
      <bpmn:incoming>Flow_Repairable</bpmn:incoming>
      <bpmn:outgoing>Flow_Draft_Approve</bpmn:outgoing>
    </bpmn:serviceTask>

    <bpmn:userTask id="Task_ApproveRepair" name="Approve repair (four-eyes)">
      <bpmn:incoming>Flow_Draft_Approve</bpmn:incoming>
      <bpmn:outgoing>Flow_Approve_Screen</bpmn:outgoing>
    </bpmn:userTask>

    <bpmn:serviceTask id="Task_SanctionsRescreen" name="Sanctions &amp; compliance re-screen">
      <bpmn:incoming>Flow_Approve_Screen</bpmn:incoming>
      <bpmn:outgoing>Flow_Screen_Apply</bpmn:outgoing>
    </bpmn:serviceTask>

    <bpmn:serviceTask id="Task_ApplyRepair" name="Apply repair &amp; release payment">
      <bpmn:incoming>Flow_Screen_Apply</bpmn:incoming>
      <bpmn:outgoing>Flow_Apply_Notify</bpmn:outgoing>
    </bpmn:serviceTask>

    <bpmn:serviceTask id="Task_NotifyParties" name="Notify originator &amp; beneficiary bank">
      <bpmn:incoming>Flow_Apply_Notify</bpmn:incoming>
      <bpmn:outgoing>Flow_Notify_Record</bpmn:outgoing>
    </bpmn:serviceTask>

    <bpmn:serviceTask id="Task_RecordResolution" name="Record resolution &amp; evidence">
      <bpmn:incoming>Flow_Notify_Record</bpmn:incoming>
      <bpmn:outgoing>Flow_Record_Resolved</bpmn:outgoing>
    </bpmn:serviceTask>

    <bpmn:endEvent id="End_Resolved" name="Exception resolved">
      <bpmn:incoming>Flow_Record_Resolved</bpmn:incoming>
    </bpmn:endEvent>

    <bpmn:serviceTask id="Task_DraftReturn" name="Draft payment return (pacs.004)">
      <bpmn:incoming>Flow_Unrepairable</bpmn:incoming>
      <bpmn:outgoing>Flow_Return_Approve</bpmn:outgoing>
    </bpmn:serviceTask>

    <bpmn:userTask id="Task_ApproveReturn" name="Approve return (four-eyes)">
      <bpmn:incoming>Flow_Return_Approve</bpmn:incoming>
      <bpmn:outgoing>Flow_Approve_Execute</bpmn:outgoing>
    </bpmn:userTask>

    <bpmn:serviceTask id="Task_ExecuteReturn" name="Execute return &amp; notify">
      <bpmn:incoming>Flow_Approve_Execute</bpmn:incoming>
      <bpmn:outgoing>Flow_Execute_Returned</bpmn:outgoing>
    </bpmn:serviceTask>

    <bpmn:endEvent id="End_Returned" name="Funds returned">
      <bpmn:incoming>Flow_Execute_Returned</bpmn:incoming>
    </bpmn:endEvent>

    <bpmn:sequenceFlow id="Flow_Start_Enrich" sourceRef="Start_ExceptionReceived" targetRef="Task_EnrichPayment"/>
    <bpmn:sequenceFlow id="Flow_Enrich_Assess" sourceRef="Task_EnrichPayment" targetRef="Task_AssessRepairability"/>
    <bpmn:sequenceFlow id="Flow_Assess_Gateway" sourceRef="Task_AssessRepairability" targetRef="Gateway_Repairable"/>
    <bpmn:sequenceFlow id="Flow_Repairable" name="repairable" sourceRef="Gateway_Repairable" targetRef="Task_DraftRepair">
      <bpmn:conditionExpression xsi:type="bpmn:tFormalExpression"
        language="https://www.omg.org/spec/DMN/20191111/FEEL/">beneficiary.repair_verdict = "repairable"</bpmn:conditionExpression>
    </bpmn:sequenceFlow>
    <bpmn:sequenceFlow id="Flow_Unrepairable" name="unrepairable" sourceRef="Gateway_Repairable" targetRef="Task_DraftReturn">
      <bpmn:conditionExpression xsi:type="bpmn:tFormalExpression"
        language="https://www.omg.org/spec/DMN/20191111/FEEL/">beneficiary.repair_verdict = "unrepairable"</bpmn:conditionExpression>
    </bpmn:sequenceFlow>
    <bpmn:sequenceFlow id="Flow_NeedsInfo" name="needs info (default)" sourceRef="Gateway_Repairable" targetRef="Task_ObtainInfo"/>
    <bpmn:sequenceFlow id="Flow_Info_Assess" sourceRef="Task_ObtainInfo" targetRef="Task_AssessRepairability"/>
    <bpmn:sequenceFlow id="Flow_Draft_Approve" sourceRef="Task_DraftRepair" targetRef="Task_ApproveRepair"/>
    <bpmn:sequenceFlow id="Flow_Approve_Screen" sourceRef="Task_ApproveRepair" targetRef="Task_SanctionsRescreen"/>
    <bpmn:sequenceFlow id="Flow_Screen_Apply" sourceRef="Task_SanctionsRescreen" targetRef="Task_ApplyRepair"/>
    <bpmn:sequenceFlow id="Flow_Apply_Notify" sourceRef="Task_ApplyRepair" targetRef="Task_NotifyParties"/>
    <bpmn:sequenceFlow id="Flow_Notify_Record" sourceRef="Task_NotifyParties" targetRef="Task_RecordResolution"/>
    <bpmn:sequenceFlow id="Flow_Record_Resolved" sourceRef="Task_RecordResolution" targetRef="End_Resolved"/>
    <bpmn:sequenceFlow id="Flow_Return_Approve" sourceRef="Task_DraftReturn" targetRef="Task_ApproveReturn"/>
    <bpmn:sequenceFlow id="Flow_Approve_Execute" sourceRef="Task_ApproveReturn" targetRef="Task_ExecuteReturn"/>
    <bpmn:sequenceFlow id="Flow_Execute_Returned" sourceRef="Task_ExecuteReturn" targetRef="End_Returned"/>
  </bpmn:process>

  <bpmndi:BPMNDiagram id="Diagram_WireRepair">
    <bpmndi:BPMNPlane id="Plane_WireRepair" bpmnElement="Process_WireRepairStandard">
      <bpmndi:BPMNShape id="S_Start" bpmnElement="Start_ExceptionReceived"><dc:Bounds x="152" y="182" width="36" height="36"/></bpmndi:BPMNShape>
      <bpmndi:BPMNShape id="S_Enrich" bpmnElement="Task_EnrichPayment"><dc:Bounds x="240" y="160" width="120" height="80"/></bpmndi:BPMNShape>
      <bpmndi:BPMNShape id="S_Assess" bpmnElement="Task_AssessRepairability"><dc:Bounds x="410" y="160" width="120" height="80"/></bpmndi:BPMNShape>
      <bpmndi:BPMNShape id="S_Gw" bpmnElement="Gateway_Repairable" isMarkerVisible="true"><dc:Bounds x="585" y="175" width="50" height="50"/></bpmndi:BPMNShape>
      <bpmndi:BPMNShape id="S_ObtainInfo" bpmnElement="Task_ObtainInfo"><dc:Bounds x="410" y="320" width="120" height="80"/></bpmndi:BPMNShape>
      <bpmndi:BPMNShape id="S_DraftRepair" bpmnElement="Task_DraftRepair"><dc:Bounds x="690" y="160" width="120" height="80"/></bpmndi:BPMNShape>
      <bpmndi:BPMNShape id="S_ApproveRepair" bpmnElement="Task_ApproveRepair"><dc:Bounds x="860" y="160" width="120" height="80"/></bpmndi:BPMNShape>
      <bpmndi:BPMNShape id="S_Sanctions" bpmnElement="Task_SanctionsRescreen"><dc:Bounds x="1030" y="160" width="120" height="80"/></bpmndi:BPMNShape>
      <bpmndi:BPMNShape id="S_ApplyRepair" bpmnElement="Task_ApplyRepair"><dc:Bounds x="1200" y="160" width="120" height="80"/></bpmndi:BPMNShape>
      <bpmndi:BPMNShape id="S_Notify" bpmnElement="Task_NotifyParties"><dc:Bounds x="1370" y="160" width="120" height="80"/></bpmndi:BPMNShape>
      <bpmndi:BPMNShape id="S_Record" bpmnElement="Task_RecordResolution"><dc:Bounds x="1540" y="160" width="120" height="80"/></bpmndi:BPMNShape>
      <bpmndi:BPMNShape id="S_EndResolved" bpmnElement="End_Resolved"><dc:Bounds x="1712" y="182" width="36" height="36"/></bpmndi:BPMNShape>
      <bpmndi:BPMNShape id="S_DraftReturn" bpmnElement="Task_DraftReturn"><dc:Bounds x="690" y="440" width="120" height="80"/></bpmndi:BPMNShape>
      <bpmndi:BPMNShape id="S_ApproveReturn" bpmnElement="Task_ApproveReturn"><dc:Bounds x="860" y="440" width="120" height="80"/></bpmndi:BPMNShape>
      <bpmndi:BPMNShape id="S_ExecuteReturn" bpmnElement="Task_ExecuteReturn"><dc:Bounds x="1030" y="440" width="120" height="80"/></bpmndi:BPMNShape>
      <bpmndi:BPMNShape id="S_EndReturned" bpmnElement="End_Returned"><dc:Bounds x="1200" y="462" width="36" height="36"/></bpmndi:BPMNShape>
      <bpmndi:BPMNEdge id="E_Start_Enrich" bpmnElement="Flow_Start_Enrich"><di:waypoint x="188" y="200"/><di:waypoint x="240" y="200"/></bpmndi:BPMNEdge>
      <bpmndi:BPMNEdge id="E_Enrich_Assess" bpmnElement="Flow_Enrich_Assess"><di:waypoint x="360" y="200"/><di:waypoint x="410" y="200"/></bpmndi:BPMNEdge>
      <bpmndi:BPMNEdge id="E_Assess_Gw" bpmnElement="Flow_Assess_Gateway"><di:waypoint x="530" y="200"/><di:waypoint x="585" y="200"/></bpmndi:BPMNEdge>
      <bpmndi:BPMNEdge id="E_Repairable" bpmnElement="Flow_Repairable"><di:waypoint x="635" y="200"/><di:waypoint x="690" y="200"/></bpmndi:BPMNEdge>
      <bpmndi:BPMNEdge id="E_NeedsInfo" bpmnElement="Flow_NeedsInfo"><di:waypoint x="610" y="225"/><di:waypoint x="610" y="360"/><di:waypoint x="530" y="360"/></bpmndi:BPMNEdge>
      <bpmndi:BPMNEdge id="E_Info_Assess" bpmnElement="Flow_Info_Assess"><di:waypoint x="470" y="320"/><di:waypoint x="470" y="240"/></bpmndi:BPMNEdge>
      <bpmndi:BPMNEdge id="E_Draft_Approve" bpmnElement="Flow_Draft_Approve"><di:waypoint x="810" y="200"/><di:waypoint x="860" y="200"/></bpmndi:BPMNEdge>
      <bpmndi:BPMNEdge id="E_Approve_Screen" bpmnElement="Flow_Approve_Screen"><di:waypoint x="980" y="200"/><di:waypoint x="1030" y="200"/></bpmndi:BPMNEdge>
      <bpmndi:BPMNEdge id="E_Screen_Apply" bpmnElement="Flow_Screen_Apply"><di:waypoint x="1150" y="200"/><di:waypoint x="1200" y="200"/></bpmndi:BPMNEdge>
      <bpmndi:BPMNEdge id="E_Apply_Notify" bpmnElement="Flow_Apply_Notify"><di:waypoint x="1320" y="200"/><di:waypoint x="1370" y="200"/></bpmndi:BPMNEdge>
      <bpmndi:BPMNEdge id="E_Notify_Record" bpmnElement="Flow_Notify_Record"><di:waypoint x="1490" y="200"/><di:waypoint x="1540" y="200"/></bpmndi:BPMNEdge>
      <bpmndi:BPMNEdge id="E_Record_Resolved" bpmnElement="Flow_Record_Resolved"><di:waypoint x="1660" y="200"/><di:waypoint x="1712" y="200"/></bpmndi:BPMNEdge>
      <bpmndi:BPMNEdge id="E_Return_Approve" bpmnElement="Flow_Return_Approve"><di:waypoint x="810" y="480"/><di:waypoint x="860" y="480"/></bpmndi:BPMNEdge>
      <bpmndi:BPMNEdge id="E_Approve_Execute" bpmnElement="Flow_Approve_Execute"><di:waypoint x="980" y="480"/><di:waypoint x="1030" y="480"/></bpmndi:BPMNEdge>
      <bpmndi:BPMNEdge id="E_Execute_Returned" bpmnElement="Flow_Execute_Returned"><di:waypoint x="1150" y="480"/><di:waypoint x="1200" y="480"/></bpmndi:BPMNEdge>
    </bpmndi:BPMNPlane>
  </bpmndi:BPMNDiagram>
</bpmn:definitions>
```

## 8. Notes

- The XML deliberately carries **no Amendia extension elements**: all execution metadata (capabilities, HITL, tools, bindings) lives in the annotation manifest per ADR-002 D1, keeping the bank's BPMN byte-stable. The DI section is included so bpmn-js renders it in the dashboard as-is.
- The `Task_ObtainInfo → Task_AssessRepairability` loop is legal within the Iteration-1 subset (it is plain sequence flow); the plan compiler must represent it as a cycle in the execution plan, and the conformance checker allows re-activation of `Task_AssessRepairability` only via this edge.
- **Post-repair steps are sequential** (`Task_ApplyRepair → Task_NotifyParties → Task_RecordResolution → End_Resolved`). An earlier draft used a `parallelGateway` fork/join to run notify and record concurrently; the Step 3 agent-runtime plan compiler does not support parallel gateways, so the seed was linearized (both steps still run, one after the other). `RecordResolution` depends only on `repair` + `screening`, both produced upstream, so ordering is safe. Re-introducing parallelism is a future-iteration change gated on parallel-gateway support in the compiler.
- The generator (ADR-006 D4) should randomize `reason_codes` across AC01 / AC04 / RC01 / BE04 and vary amounts and attachment presence, so triage rules, the assess capability, and all three gateway branches get exercised.
