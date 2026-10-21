from datetime import UTC, datetime
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, File, Form, HTTPException, Query, Request, UploadFile
from fastapi.responses import FileResponse
from sqlalchemy import func, select
from sqlalchemy.orm import joinedload
from app.api.deps import CurrentUser, DbSession, require_roles
from app.models.catalog import Product
from app.models.customer import User, UserRole
from app.models.prescriptions import Prescription, PrescriptionReviewAudit
from app.schemas.prescriptions import (
    CustomerPrescriptionRead,
    PrescriptionReviewAuditRead,
    PrescriptionReviewRequest,
    PrescriptionStaffPage,
    PrescriptionStaffRead,
)
from app.services.prescriptions import (
    MAX_PRESCRIPTION_BYTES,
    latest_prescriptions_for_products,
    private_document_path,
    remove_private_document,
    validate_document,
    write_private_document,
)
from app.core.rate_limit import limiter

router = APIRouter(tags=["prescriptions"])
StaffUser = Annotated[User, Depends(require_roles(UserRole.ADMIN, UserRole.PHARMACIST))]


def _customer_read(row: Prescription) -> CustomerPrescriptionRead:
    return CustomerPrescriptionRead(
        id=row.id,
        product_id=row.product_id,
        product_name=row.product.name,
        product_slug=row.product.slug,
        status=row.status,
        review_note=row.review_note,
        created_at=row.created_at,
        reviewed_at=row.reviewed_at,
    )


def _staff_read(row: Prescription) -> PrescriptionStaffRead:
    return PrescriptionStaffRead(
        id=row.id,
        customer_id=row.customer_id,
        customer_name=row.customer.full_name,
        customer_email=row.customer.email,
        customer_phone=row.customer.phone,
        product_id=row.product_id,
        product_name=row.product.name,
        media_type=row.media_type,
        file_size=row.file_size,
        status=row.status,
        review_note=row.review_note,
        created_at=row.created_at,
        reviewed_at=row.reviewed_at,
    )


@router.post("/prescriptions", response_model=CustomerPrescriptionRead, status_code=201)
@limiter.limit("10/minute")
async def upload_prescription(
    request: Request,
    user: CurrentUser,
    db: DbSession,
    product_id: Annotated[UUID, Form()],
    file: Annotated[UploadFile, File()],
) -> CustomerPrescriptionRead:
    if user.role != UserRole.CUSTOMER.value:
        raise HTTPException(status_code=403, detail="Only customer accounts can upload prescriptions")
    product = db.scalar(
        select(Product).where(Product.id == product_id, Product.is_active.is_(True))
    )
    if product is None or not product.prescription_required:
        raise HTTPException(status_code=404, detail="Prescription upload is unavailable for this listing")

    try:
        data = await file.read(MAX_PRESCRIPTION_BYTES + 1)
        media_type, extension = validate_document(file.content_type, data)
    except ValueError as error:
        raise HTTPException(status_code=422, detail=str(error)) from error
    finally:
        await file.close()

    storage_key, path = write_private_document(data, extension)
    prescription = Prescription(
        customer_id=user.id,
        product_id=product.id,
        storage_key=storage_key,
        media_type=media_type,
        file_size=len(data),
        status="pending",
    )
    db.add(prescription)
    try:
        db.commit()
        db.refresh(prescription)
    except Exception:
        db.rollback()
        remove_private_document(path)
        raise
    return _customer_read(
        db.scalar(
            select(Prescription)
            .where(Prescription.id == prescription.id)
            .options(joinedload(Prescription.product))
        )
    )


@router.get("/prescriptions", response_model=list[CustomerPrescriptionRead])
def list_my_prescriptions(
    user: CurrentUser,
    db: DbSession,
    product_id: Annotated[UUID | None, Query()] = None,
) -> list[CustomerPrescriptionRead]:
    filters = [Prescription.customer_id == user.id]
    if product_id:
        filters.append(Prescription.product_id == product_id)
    rows = db.scalars(
        select(Prescription)
        .where(*filters)
        .options(joinedload(Prescription.product))
        .order_by(Prescription.created_at.desc(), Prescription.id.desc())
    ).unique().all()
    return [_customer_read(row) for row in rows]


@router.get("/prescriptions/{prescription_id}/file")
def download_prescription(
    prescription_id: UUID,
    user: CurrentUser,
    db: DbSession,
):
    row = db.get(Prescription, prescription_id)
    if row is None:
        raise HTTPException(status_code=404, detail="Prescription not found")
    if user.role not in (UserRole.ADMIN.value, UserRole.PHARMACIST.value) and row.customer_id != user.id:
        raise HTTPException(status_code=404, detail="Prescription not found")
    if user.role not in (UserRole.CUSTOMER.value, UserRole.ADMIN.value, UserRole.PHARMACIST.value):
        raise HTTPException(status_code=403, detail="Insufficient permissions")
    path = private_document_path(row)
    if not path.is_file():
        raise HTTPException(status_code=404, detail="Prescription file is unavailable")
    extension = ".pdf" if row.media_type == "application/pdf" else ".png" if row.media_type == "image/png" else ".jpg"
    return FileResponse(
        path,
        media_type="application/octet-stream",
        filename=f"prescription-{row.id}{extension}",
        headers={"Cache-Control": "no-store, private", "X-Content-Type-Options": "nosniff"},
    )


admin_router = APIRouter(prefix="/admin/prescriptions", tags=["prescription review"])


@admin_router.get("", response_model=PrescriptionStaffPage)
def list_prescriptions_for_review(
    _staff: StaffUser,
    db: DbSession,
    status: Annotated[str, Query(pattern="^(pending|approved|rejected|all)$")] = "pending",
    page: Annotated[int, Query(ge=1)] = 1,
    page_size: Annotated[int, Query(ge=1, le=50)] = 20,
) -> PrescriptionStaffPage:
    filters = [] if status == "all" else [Prescription.status == status]
    total = db.scalar(select(func.count(Prescription.id)).where(*filters)) or 0
    rows = db.scalars(
        select(Prescription)
        .where(*filters)
        .options(joinedload(Prescription.customer), joinedload(Prescription.product))
        .order_by(Prescription.created_at.asc(), Prescription.id.asc())
        .offset((page - 1) * page_size)
        .limit(page_size)
    ).unique().all()
    return PrescriptionStaffPage(
        items=[_staff_read(row) for row in rows], total=total, page=page, page_size=page_size
    )


@admin_router.patch("/{prescription_id}/review", response_model=PrescriptionStaffRead)
def review_prescription(
    prescription_id: UUID,
    body: PrescriptionReviewRequest,
    staff: StaffUser,
    db: DbSession,
) -> PrescriptionStaffRead:
    row = db.scalars(
        select(Prescription)
        .where(Prescription.id == prescription_id)
        .options(joinedload(Prescription.customer), joinedload(Prescription.product))
        .with_for_update()
    ).unique().one_or_none()
    if row is None:
        raise HTTPException(status_code=404, detail="Prescription not found")
    note = body.note.strip() if body.note else None
    if body.status == "rejected" and not note:
        raise HTTPException(status_code=422, detail="Add a brief reason when rejecting a prescription")
    if row.status == body.status and row.review_note == note:
        return _staff_read(row)

    previous_status = row.status
    row.status = body.status
    row.reviewer_user_id = staff.id
    row.review_note = note
    row.reviewed_at = datetime.now(UTC)
    db.add(
        PrescriptionReviewAudit(
            prescription_id=row.id,
            reviewer_user_id=staff.id,
            previous_status=previous_status,
            status=body.status,
            note=note,
        )
    )
    db.commit()
    db.refresh(row)
    return _staff_read(row)


@admin_router.get("/{prescription_id}/history", response_model=list[PrescriptionReviewAuditRead])
def prescription_review_history(
    prescription_id: UUID,
    _staff: StaffUser,
    db: DbSession,
) -> list[PrescriptionReviewAuditRead]:
    if db.get(Prescription, prescription_id) is None:
        raise HTTPException(status_code=404, detail="Prescription not found")
    rows = db.execute(
        select(PrescriptionReviewAudit, User.full_name)
        .join(User, User.id == PrescriptionReviewAudit.reviewer_user_id)
        .where(PrescriptionReviewAudit.prescription_id == prescription_id)
        .order_by(PrescriptionReviewAudit.created_at.desc(), PrescriptionReviewAudit.id.desc())
    ).all()
    return [
        PrescriptionReviewAuditRead(
            id=audit.id,
            reviewer_name=name,
            previous_status=audit.previous_status,
            status=audit.status,
            note=audit.note,
            created_at=audit.created_at,
        )
        for audit, name in rows
    ]
