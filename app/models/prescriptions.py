from datetime import datetime
from uuid import UUID, uuid4

from sqlalchemy import CheckConstraint, DateTime, ForeignKey, Index, Integer, String, Uuid, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base


class Prescription(Base):
    __tablename__ = "prescriptions"
    __table_args__ = (
        CheckConstraint(
            "status IN ('pending', 'approved', 'rejected')",
            name="ck_prescriptions_status_valid",
        ),
        CheckConstraint("file_size BETWEEN 1 AND 5242880", name="ck_prescriptions_file_size_valid"),
        Index("ix_prescriptions_customer_product_created", "customer_id", "product_id", "created_at"),
        Index("ix_prescriptions_status_created", "status", "created_at"),
    )

    id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid4)
    customer_id: Mapped[UUID] = mapped_column(
        ForeignKey("users.id", ondelete="RESTRICT"), nullable=False, index=True
    )
    product_id: Mapped[UUID] = mapped_column(
        ForeignKey("products.id", ondelete="RESTRICT"), nullable=False, index=True
    )
    storage_key: Mapped[str] = mapped_column(String(48), unique=True, nullable=False)
    media_type: Mapped[str] = mapped_column(String(40), nullable=False)
    file_size: Mapped[int] = mapped_column(Integer, nullable=False)
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="pending")
    reviewer_user_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("users.id", ondelete="RESTRICT"), nullable=True, index=True
    )
    review_note: Mapped[str | None] = mapped_column(String(500), nullable=True)
    reviewed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )

    customer: Mapped["User"] = relationship(foreign_keys=[customer_id])
    product: Mapped["Product"] = relationship()
    reviewer: Mapped["User | None"] = relationship(foreign_keys=[reviewer_user_id])
    reviews: Mapped[list["PrescriptionReviewAudit"]] = relationship(
        back_populates="prescription", cascade="all, delete-orphan", order_by="PrescriptionReviewAudit.created_at"
    )


class PrescriptionReviewAudit(Base):
    __tablename__ = "prescription_review_audits"
    __table_args__ = (
        CheckConstraint(
            "status IN ('approved', 'rejected')",
            name="ck_prescription_review_audits_status_valid",
        ),
        Index("ix_prescription_review_audits_prescription_created", "prescription_id", "created_at"),
    )

    id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid4)
    prescription_id: Mapped[UUID] = mapped_column(
        ForeignKey("prescriptions.id", ondelete="CASCADE"), nullable=False
    )
    reviewer_user_id: Mapped[UUID] = mapped_column(
        ForeignKey("users.id", ondelete="RESTRICT"), nullable=False, index=True
    )
    previous_status: Mapped[str] = mapped_column(String(20), nullable=False)
    status: Mapped[str] = mapped_column(String(20), nullable=False)
    note: Mapped[str | None] = mapped_column(String(500), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    prescription: Mapped[Prescription] = relationship(back_populates="reviews")
    reviewer: Mapped["User"] = relationship()
