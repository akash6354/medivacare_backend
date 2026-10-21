from fastapi import HTTPException

from app.models.prescriptions import Prescription

ORDER_STATUS_TRANSITIONS: dict[str, set[str]] = {
    "placed": {"confirmed", "cancelled"},
    "confirmed": {"processing", "cancelled"},
    "processing": {"shipped", "cancelled"},
    "shipped": {"out_for_delivery", "returned"},
    "out_for_delivery": {"delivered", "returned"},
    "delivered": {"returned"},
}


def require_approved_prescriptions(db, order) -> None:
    for item in order.items:
        if not item.prescription_required:
            continue
        prescription = db.get(Prescription, item.prescription_id) if item.prescription_id else None
        if (
            prescription is None
            or prescription.status != "approved"
            or prescription.customer_id != order.customer_id
            or prescription.product_id != item.product_id
        ):
            raise HTTPException(
                status_code=409,
                detail="An approved prescription linked to every prescription-flagged item is required for fulfillment",
            )
