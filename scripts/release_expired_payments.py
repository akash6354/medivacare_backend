"""Release expired online-payment reservations after reconciling Razorpay first.

Run this module periodically from Windows Task Scheduler in deployments that
need abandoned checkouts released without waiting for a customer status request.
"""
from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.orm import selectinload

from app.core.config import get_settings
from app.db.session import SessionLocal
from app.models.orders import Order, PaymentAttempt
from app.services.payments import expire_pending_attempt
from app.services.razorpay import razorpay_client


def main() -> None:
    with SessionLocal() as db:
        attempts = db.scalars(
            select(PaymentAttempt)
            .join(Order)
            .options(selectinload(PaymentAttempt.order).selectinload(Order.items))
            .where(
                Order.status == "pending_payment",
                PaymentAttempt.expires_at <= datetime.now(UTC),
                PaymentAttempt.provider_mode == get_settings().razorpay_mode,
            )
            .order_by(PaymentAttempt.expires_at.asc())
        ).unique().all()
        if not attempts:
            print("No expired payment reservations.")
            return

        client = razorpay_client()
        released = sum(expire_pending_attempt(db, attempt, client) for attempt in attempts)
        print(f"Released {released} expired payment reservation(s); unresolved attempts remain reserved.")


if __name__ == "__main__":
    main()
