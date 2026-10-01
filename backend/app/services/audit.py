from sqlalchemy.orm import Session

from app.models.entities import AuditLog, User


def write_audit(
    db: Session,
    user: User | None,
    action: str,
    target_type: str = "",
    target_id: str = "",
    detail: str = "",
    ip_address: str = "",
) -> None:
    db.add(
        AuditLog(
            user_id=user.id if user else None,
            username=user.username if user else "system",
            action=action,
            target_type=target_type,
            target_id=str(target_id),
            detail=detail[:2000],
            ip_address=ip_address,
        )
    )
    db.commit()
