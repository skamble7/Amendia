# app/generator.py
"""Synthetic wire-exception generator (pure, no I/O).

Given an optional set of caller-pinned fields, produces a fully-formed
``WireExceptionEnvelope`` for an unable-to-apply wire transfer. Everything the
caller does not pin is randomized within the sets the triage rules and BPMN
branches expect to see (reference doc §4 + §8).
"""
from __future__ import annotations

import random
import uuid
from datetime import datetime, timedelta, timezone
from typing import List, Optional

from app.models.api import GenerateRequest
from app.models.envelope import (
    Account,
    Agent,
    Attachment,
    MonetaryAmount,
    Party,
    PaymentDetails,
    RelatedMessage,
    Source,
    WireExceptionEnvelope,
)
from app.sample_data import CATALOG, sha256_of

# The reason codes the triage rule matches → wire-repair-standard pack.
REASON_CODES = ["AC01", "AC04", "RC01", "BE04"]

# Coherent narrative per reason code.
NARRATIVES = {
    "AC01": "Beneficiary account not found at beneficiary bank; possible digit "
    "transposition per attached screenshot.",
    "AC04": "Beneficiary account is closed at the beneficiary bank; funds cannot "
    "be applied and require repair or return.",
    "RC01": "Bank identifier (BIC/routing) is incorrect or unreachable; the wire "
    "could not be delivered to the intended beneficiary bank.",
    "BE04": "Missing or invalid creditor address; beneficiary bank cannot apply "
    "the funds without complete party details.",
}

# Small party / agent pools for variety.
_DEBTORS = [
    "Northline Industrial Supply LLC",
    "Cedar Peak Trading Co",
    "Atlas Marine Logistics Inc",
    "Brightwater Foods Corp",
    "Sterling Ridge Manufacturing",
]
_CREDITORS = [
    ("Kestrel Components GmbH", "KSTLDEFF", "DE44500105175407324931"),
    ("Meridian Textiles SA", "MERISESS", "ES9121000418450200051332"),
    ("Halcyon Robotics BV", "HALCNL2A", "NL91ABNA0417164300"),
    ("Aurora Chemicals SpA", "AUROITMM", "IT60X0542811101000000123456"),
    ("Novena Pharma SAS", "NOVEFRPP", "FR7630006000011234567890189"),
]
_DEBTOR_AGENTS = ["ALPHUS33", "ALPHUS44", "NORTUS31"]
_CURRENCIES_DEFAULT = "USD"


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _new_exception_id(now: datetime) -> str:
    # EXC-<year>-<6-digit random>. Uniqueness is enforced by the DB index;
    # the caller retries on the (rare) collision.
    return f"EXC-{now.year}-{random.randint(0, 999_999):06d}"


def _choose_attachment_ids(include_attachments: Optional[bool]) -> List[str]:
    """Decide which canned attachments to include.

    Pinned True → both; False → none; unset → varied (both / one / none).
    """
    if include_attachments is True:
        return ["att-1", "att-2"]
    if include_attachments is False:
        return []
    return random.choice([["att-1", "att-2"], ["att-1"], ["att-2"], []])


def _build_attachments(exception_id: str, base_url: str, attachment_ids: List[str]) -> List[Attachment]:
    base = base_url.rstrip("/")
    out: List[Attachment] = []
    for aid in attachment_ids:
        spec = CATALOG[aid]
        out.append(
            Attachment(
                attachment_id=spec.attachment_id,
                name=spec.name,
                media_type=spec.media_type,
                sha256=sha256_of(aid),
                fetch_url=f"{base}/exceptions/{exception_id}/attachments/{spec.attachment_id}",
            )
        )
    return out


def generate_envelope(
    req: GenerateRequest,
    base_url: str,
    default_tenant: str,
    now: Optional[datetime] = None,
) -> WireExceptionEnvelope:
    """Produce one synthetic unable-to-apply wire exception envelope."""
    now = now or _now()
    tenant = req.tenant or default_tenant

    reason_code = req.reason_code or random.choice(REASON_CODES)
    amount = req.amount if req.amount is not None else round(random.uniform(10_000, 5_000_000), 2)
    currency = req.currency or _CURRENCIES_DEFAULT

    exception_id = _new_exception_id(now)
    debtor_name = random.choice(_DEBTORS)
    debtor_bic = random.choice(_DEBTOR_AGENTS)
    creditor_name, creditor_bic, creditor_iban = random.choice(_CREDITORS)
    value_date = (now - timedelta(days=random.randint(1, 3))).date().isoformat()

    payment = PaymentDetails(
        msg_type="pacs.008.001.10",
        uetr=str(uuid.uuid4()),
        instruction_id=f"BKALPHA{now:%Y%m%d}INS{random.randint(0, 9999):04d}",
        end_to_end_id=f"INV-{random.randint(10000, 99999)}-PAY",
        settlement_amount=MonetaryAmount(currency=currency, value=amount),
        value_date=value_date,
        debtor=Party(name=debtor_name),
        debtor_agent=Agent(bic=debtor_bic),
        creditor=Party(name=creditor_name, account=Account(id=creditor_iban, scheme="IBAN")),
        creditor_agent=Agent(bic=creditor_bic),
        charges="SHA",
    )

    related = [
        RelatedMessage(
            type="camt.026",
            id=f"CASE-{creditor_bic[:4]}-{random.randint(10000, 99999)}",
            assigner_bic=creditor_bic,
        )
    ]

    attachments = _build_attachments(
        exception_id, base_url, _choose_attachment_ids(req.include_attachments)
    )

    return WireExceptionEnvelope(
        exception_id=exception_id,
        tenant=tenant,
        source=Source(system="payment-hub-sim", channel="swift"),
        received_at=now.strftime("%Y-%m-%dT%H:%M:%SZ"),
        exception_type="unable_to_apply",
        reason_codes=[reason_code],
        reason_narrative=NARRATIVES[reason_code],
        status="open",
        payment=payment,
        related_messages=related,
        attachments=attachments,
    )
