"""Source availability and selected deadline; never supplier eligibility."""

from procurement.sources.eis_223_archive import Eis223NoticeSnapshot, TimeFact


def deadline223(notice: Eis223NoticeSnapshot) -> TimeFact:
    if notice.document_type != "purchaseNotice":
        return notice.deadline
    if notice.selected_deadline is None:
        raise ValueError("GENERIC_SELECTED_DEADLINE_MISSING")
    return notice.selected_deadline


def unavailable223(notice: Eis223NoticeSnapshot) -> tuple[str, ...]:
    """Confirmed hidden/invalidated records are unavailable, not cancelled procedures."""
    if notice.document_type != "purchaseNotice":
        return ()
    reasons = []
    if notice.hide_purchase_raw and notice.hide_purchase_raw.value in {"true", "1"}:
        reasons.append("SOURCE_PURCHASE_HIDDEN")
    if (
        notice.hide_purchase_customer_accredited_raw
        and notice.hide_purchase_customer_accredited_raw.value in {"true", "1"}
    ):
        reasons.append("SOURCE_PURCHASE_ACCREDITED_ONLY")
    if notice.status_raw.value == "I":
        reasons.append("SOURCE_RECORD_INVALIDATED")
    return tuple(reasons)
