from __future__ import annotations

from sqlalchemy import text
from sqlalchemy.orm import Session

from app.core.database import Base, SessionLocal, engine
from app.core.security import hash_password
from app.models.entities import CaseClassification, Role, ScreeningRule, User
from app.services.rules import seed_rule_rows


ROLE_DEFS = {
    "admin": ("系统管理员", "all,read,import,screen,review,export,audit,admin"),
    "prosecutor": ("检察官", "read,screen,review,export"),
    "reviewer": ("标注员", "read,review"),
    "viewer": ("只读审阅员", "read"),
}

USER_DEFS = [
    ("admin", "系统管理员", "admin123", "admin"),
    ("prosecutor", "承办检察官", "prosecutor123", "prosecutor"),
    ("reviewer", "线索标注员", "reviewer123", "reviewer"),
    ("viewer", "只读审阅员", "viewer123", "viewer"),
]


def seed_roles_users(db: Session) -> None:
    roles = {}
    for name, (display, perms) in ROLE_DEFS.items():
        role = db.query(Role).filter(Role.name == name).first()
        if not role:
            role = Role(name=name, display_name=display, permissions=perms)
            db.add(role)
            db.flush()
        else:
            role.display_name = display
            role.permissions = perms
        roles[name] = role

    for username, display_name, password, role_name in USER_DEFS:
        user = db.query(User).filter(User.username == username).first()
        if not user:
            db.add(
                User(
                    username=username,
                    display_name=display_name,
                    password_hash=hash_password(password),
                    role_id=roles[role_name].id,
                    is_active=True,
                )
            )
        else:
            user.display_name = display_name
            user.password_hash = hash_password(password)
            user.role_id = roles[role_name].id
            user.is_active = True
    db.commit()


def seed_rules(db: Session) -> None:
    db.query(ScreeningRule).filter(ScreeningRule.module == "wage").delete(synchronize_session=False)
    db.query(CaseClassification).filter(CaseClassification.module == "wage").delete(synchronize_session=False)
    legacy_map = {
        "家暴弱势群体": ("vulnerable", "其他"),
        "执法不规范": ("administrative", "未按程序处罚"),
        "生态环境": ("public_interest", "生态环境和资源保护"),
        "食品药品": ("public_interest", "食品药品安全"),
        "个人信息": ("public_interest", "个人信息保护"),
        "未成年人": ("public_interest", "未成年人保护"),
        "无障碍": ("public_interest", "无障碍环境建设"),
        "文物文化": ("public_interest", "文物和文化遗产保护"),
    }
    for name, (module, domain) in legacy_map.items():
        existing = db.query(ScreeningRule).filter(ScreeningRule.name == name).first()
        if existing:
            existing.module = module
            existing.domain = domain
    for row in seed_rule_rows():
        existing = db.query(ScreeningRule).filter(ScreeningRule.name == row["name"]).first()
        if not existing:
            db.add(ScreeningRule(**row))
        else:
            existing.module = row.get("module", existing.module or "public_interest")
            existing.domain = row["domain"]
            existing.weight = row["weight"]
            existing.enabled = row.get("enabled", existing.enabled)
            merged = []
            for keyword in f"{existing.keywords},{row['keywords']}".split(","):
                keyword = keyword.strip()
                if keyword and keyword not in merged:
                    merged.append(keyword)
            existing.keywords = ",".join(merged)
    db.commit()


def _sqlite_columns(table: str) -> set[str]:
    if not engine.url.drivername.startswith("sqlite"):
        return set()
    with engine.begin() as conn:
        rows = conn.execute(text(f"PRAGMA table_info({table})")).fetchall()
    return {row[1] for row in rows}


def migrate_schema() -> None:
    if not engine.url.drivername.startswith("sqlite"):
        return
    work_order_columns = _sqlite_columns("work_orders")
    rule_columns = _sqlite_columns("screening_rules")
    cluster_columns = _sqlite_columns("event_clusters")
    with engine.begin() as conn:
        for table in ("alert_rules", "alert_events", "push_items", "legal_knowledge", "analysis_reports"):
            conn.execute(text(f"DROP TABLE IF EXISTS {table}"))
        if "host_unit" not in work_order_columns:
            conn.execute(text("ALTER TABLE work_orders ADD COLUMN host_unit VARCHAR(255) DEFAULT '' NOT NULL"))
        if "received_at" not in work_order_columns:
            conn.execute(text("ALTER TABLE work_orders ADD COLUMN received_at DATETIME"))
        if "extra_fields" not in work_order_columns:
            conn.execute(text("ALTER TABLE work_orders ADD COLUMN extra_fields TEXT DEFAULT '[]' NOT NULL"))
        if "exported_at" not in work_order_columns:
            conn.execute(text("ALTER TABLE work_orders ADD COLUMN exported_at DATETIME"))
        if "exported_by" not in work_order_columns:
            conn.execute(text("ALTER TABLE work_orders ADD COLUMN exported_by VARCHAR(80) DEFAULT '' NOT NULL"))
        if "export_context" not in work_order_columns:
            conn.execute(text("ALTER TABLE work_orders ADD COLUMN export_context VARCHAR(120) DEFAULT '' NOT NULL"))
        if "module" not in rule_columns:
            conn.execute(text("ALTER TABLE screening_rules ADD COLUMN module VARCHAR(40) DEFAULT 'public_interest' NOT NULL"))
        if "representative_order_id" not in cluster_columns:
            conn.execute(text("ALTER TABLE event_clusters ADD COLUMN representative_order_id INTEGER"))
        if "match_reason" not in cluster_columns:
            conn.execute(text("ALTER TABLE event_clusters ADD COLUMN match_reason TEXT DEFAULT '' NOT NULL"))
        conn.execute(text("DELETE FROM screening_rules WHERE module = 'wage'"))
        conn.execute(text("DELETE FROM case_classifications WHERE module = 'wage'"))
        conn.execute(text("UPDATE clues SET status = '待确认' WHERE status = '待复核'"))


def rebuild_search_index() -> None:
    if not engine.url.drivername.startswith("sqlite"):
        return
    try:
        with engine.begin() as conn:
            conn.execute(
                text(
                    """
                    CREATE VIRTUAL TABLE IF NOT EXISTS work_order_fts USING fts5(
                        order_no,
                        title,
                        content,
                        problem_category,
                        tags,
                        company_name,
                        location_point,
                        extra_fields,
                        tokenize='trigram'
                    )
                    """
                )
            )
            conn.execute(text("DELETE FROM work_order_fts"))
            conn.execute(
                text(
                    """
                    INSERT INTO work_order_fts(
                        rowid, order_no, title, content, problem_category, tags,
                        company_name, location_point, extra_fields
                    )
                    SELECT
                        id,
                        COALESCE(order_no, ''),
                        COALESCE(title, ''),
                        COALESCE(content, ''),
                        COALESCE(problem_category, ''),
                        COALESCE(tags, ''),
                        COALESCE(company_name, ''),
                        COALESCE(location_point, ''),
                        COALESCE(extra_fields, '')
                    FROM work_orders
                    """
                )
            )
    except Exception:
        return


def init_database() -> None:
    Base.metadata.create_all(bind=engine)
    migrate_schema()
    db = SessionLocal()
    try:
        seed_roles_users(db)
        seed_rules(db)
    finally:
        db.close()
    rebuild_search_index()


if __name__ == "__main__":
    init_database()
    print("Database initialized.")
