from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.orm import joinedload

from app.api.deps import CurrentUser, DbSession, require_roles
from app.models.customer import User, UserRole
from app.models.support import SupportTicket
from app.schemas.support import SupportTicketCreate, SupportTicketRead, SupportTicketUpdate

router = APIRouter(prefix="/support", tags=["support"])
admin_router = APIRouter(prefix="/admin/support/tickets", tags=["support administration"])
SupportStaff = Annotated[User, Depends(require_roles(UserRole.ADMIN, UserRole.SUPPORT))]


def _ticket(ticket: SupportTicket) -> SupportTicketRead:
    return SupportTicketRead(
        id=ticket.id, customer_id=ticket.customer_id, customer_name=ticket.customer.full_name,
        customer_email=ticket.customer.email, subject=ticket.subject, message=ticket.message,
        status=ticket.status, staff_note=ticket.staff_note, created_at=ticket.created_at,
        updated_at=ticket.updated_at,
    )


@router.get("/tickets", response_model=list[SupportTicketRead])
def my_tickets(user: CurrentUser, db: DbSession) -> list[SupportTicketRead]:
    rows = db.scalars(select(SupportTicket).options(joinedload(SupportTicket.customer)).where(
        SupportTicket.customer_id == user.id
    ).order_by(SupportTicket.created_at.desc())).all()
    return [_ticket(row) for row in rows]


@router.post("/tickets", response_model=SupportTicketRead, status_code=201)
def create_ticket(body: SupportTicketCreate, user: CurrentUser, db: DbSession) -> SupportTicketRead:
    ticket = SupportTicket(customer_id=user.id, subject=body.subject.strip(), message=body.message.strip())
    db.add(ticket)
    db.commit()
    db.refresh(ticket)
    return _ticket(ticket)


@admin_router.get("", response_model=list[SupportTicketRead])
def list_tickets(_staff: SupportStaff, db: DbSession) -> list[SupportTicketRead]:
    rows = db.scalars(select(SupportTicket).options(joinedload(SupportTicket.customer)).order_by(
        SupportTicket.created_at.desc()
    )).all()
    return [_ticket(row) for row in rows]


@admin_router.patch("/{ticket_id}", response_model=SupportTicketRead)
def update_ticket(ticket_id: UUID, body: SupportTicketUpdate, staff: SupportStaff, db: DbSession) -> SupportTicketRead:
    ticket = db.scalars(select(SupportTicket).options(joinedload(SupportTicket.customer)).where(
        SupportTicket.id == ticket_id
    ).with_for_update()).unique().one_or_none()
    if ticket is None:
        raise HTTPException(status_code=404, detail="Support ticket not found")
    ticket.status = body.status
    ticket.staff_note = body.staff_note.strip() if body.staff_note and body.staff_note.strip() else None
    ticket.handled_by_user_id = staff.id
    db.commit()
    db.refresh(ticket)
    return _ticket(ticket)
