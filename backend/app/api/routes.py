from __future__ import annotations

import difflib
import json
import re
import shutil
from datetime import datetime
from pathlib import Path
from uuid import uuid4

from fastapi import APIRouter, Depends, File, HTTPException, Request, UploadFile
from fastapi.responses import FileResponse
from sqlalchemy import desc, func, or_, text
from sqlalchemy.orm import Session

from app.api.deps import get_current_user, permissions, require_permission
from app.core.config import PROJECT_DIR, settings
from app.core.database import get_db
from app.core.security import create_token, verify_password
from app.models.entities import (
    AuditLog,
    CaseClassification,
    Clue,
    ClueReview,
    ClusterMember,
    EventCluster,
    ExportTask,
    ImportBatch,
    LLMConfig,
    ScreeningRule,
    User,
    WorkOrder,
)
from app.schemas.dto import (
    ClassificationBatchReviewRequest,
    ClueReviewRequest,
    DashboardSummary,
    ExportRequest,
    LLMConfigRequest,
    LoginRequest,
    LoginResponse,
    PageResponse,
    RuleCreateRequest,
    RuleUpdateRequest,
    ScreeningRunRequest,
    ScreeningRunResponse,
    SelectedExportRequest,
)
from app.services.audit import write_audit
from app.services.analysis import cluster_dict_with_assessment, cluster_intervention_assessment, performance_anomalies, trend_analysis
from app.services.exports import create_export, create_selected_export
from app.services.importer import import_workbook
from app.services.rules import MODULE_ADMINISTRATIVE, MODULE_PUBLIC_INTEREST, MODULE_VULNERABLE
from app.services.screening import run_screening
from app.init_db import rebuild_search_index


router = APIRouter(prefix="/api")


SEARCH_FIELDS = {
    "all": "全部字段",
    "order_no": "工单编号",
    "order_type": "工单类型",
    "title": "标题",
    "content": "主要内容",
    "problem_category": "问题分类",
    "tags": "标签",
    "status": "工单状态",
    "caller_name": "来电人",
    "caller_phone": "来电人电话/账号",
    "district": "被反映区",
    "town": "被反映街乡镇",
    "company_name": "企业名称",
    "host_unit": "主办单位",
    "community": "村/社区",
    "location_point": "小区点位",
    "handling_result": "办理结果",
    "reply_content": "回复内容",
    "handling_method": "处理受理方式",
    "order_nature": "工单性质",
    "is_resolved": "是否解决",
    "satisfaction": "是否满意",
    "extra_fields": "额外导入字段",
}

SEARCH_COLUMNS = {
    "order_no": WorkOrder.order_no,
    "order_type": WorkOrder.order_type,
    "title": WorkOrder.title,
    "content": WorkOrder.content,
    "problem_category": WorkOrder.problem_category,
    "tags": WorkOrder.tags,
    "status": WorkOrder.status,
    "caller_name": WorkOrder.caller_name,
    "caller_phone": WorkOrder.caller_phone,
    "district": WorkOrder.district,
    "town": WorkOrder.town,
    "company_name": WorkOrder.company_name,
    "host_unit": WorkOrder.host_unit,
    "community": WorkOrder.community,
    "location_point": WorkOrder.location_point,
    "handling_result": WorkOrder.handling_result,
    "reply_content": WorkOrder.reply_content,
    "handling_method": WorkOrder.handling_method,
    "order_nature": WorkOrder.order_nature,
    "is_resolved": WorkOrder.is_resolved,
    "satisfaction": WorkOrder.satisfaction,
    "extra_fields": WorkOrder.extra_fields,
}

SEARCH_SYNONYMS = {
    "拖欠工资": ["欠薪", "讨薪", "工资", "工钱", "劳务费", "农民工", "包工头", "欠工资", "未发工资"],
    "欠薪": ["拖欠工资", "讨薪", "工资", "工钱", "劳务费", "农民工", "包工头", "欠工资"],
    "农民工": ["务工人员", "工友", "工人", "欠薪", "讨薪", "工资"],
    "食品安全": ["食品", "餐饮", "过期", "变质", "腹泻", "三无", "无证"],
    "食品药品": ["食品", "药品", "过期", "三无", "餐饮卫生", "假药"],
    "安全生产": ["消防", "燃气", "隐患", "坍塌", "工地安全", "飞线充电"],
    "个人信息": ["隐私", "泄露", "骚扰电话", "违规收集", "验证码", "账号被盗"],
    "行政违法": ["处罚", "罚款", "执法", "程序违法", "未告知", "证据不足", "选择性执法"],
    "弱势群体": ["妇女", "儿童", "残疾人", "老人", "农民工", "赡养", "抚养"],
}

CLASSIFICATION_MODULE_PRIORITY = {
    MODULE_PUBLIC_INTEREST: 0,
    MODULE_VULNERABLE: 1,
    MODULE_ADMINISTRATIVE: 2,
}
RULE_MODULES = {MODULE_PUBLIC_INTEREST, MODULE_VULNERABLE, MODULE_ADMINISTRATIVE}


def _extra_fields(order: WorkOrder) -> list[dict[str, str]]:
    try:
        fields = json.loads(order.extra_fields or "[]")
    except json.JSONDecodeError:
        return []
    result = []
    for item in fields:
        if not isinstance(item, dict):
            continue
        name = str(item.get("name") or "").strip()
        if not name:
            continue
        value = str(item.get("value") or "")
        result.append({"name": name, "value": value})
    return result


def _search_text(order: WorkOrder, search_field: str) -> str:
    if search_field != "all" and search_field in SEARCH_FIELDS:
        return str(getattr(order, search_field, "") or "")
    return " ".join(
        [
            order.order_no or "",
            order.order_type or "",
            order.title or "",
            order.content or "",
            order.problem_category or "",
            order.tags or "",
            order.status or "",
            order.caller_name or "",
            order.caller_phone or "",
            order.district or "",
            order.town or "",
            order.company_name or "",
            order.host_unit or "",
            order.community or "",
            order.location_point or "",
            order.handling_result or "",
            order.reply_content or "",
            order.handling_method or "",
            order.order_nature or "",
            order.is_resolved or "",
            order.satisfaction or "",
            order.extra_fields or "",
        ]
    )


SEARCH_FIELD_WEIGHTS = {
    "title": 4.0,
    "problem_category": 3.4,
    "tags": 3.0,
    "content": 2.5,
    "company_name": 2.0,
    "location_point": 2.0,
    "order_no": 1.8,
    "caller_name": 1.4,
    "caller_phone": 1.4,
    "host_unit": 1.4,
    "handling_result": 1.0,
    "reply_content": 1.0,
    "extra_fields": 1.0,
}
FTS_COLUMNS = {"order_no", "title", "content", "problem_category", "tags", "company_name", "location_point", "extra_fields"}


def _normalize_search_text(value: str) -> str:
    return "".join(str(value or "").replace("，", " ").replace(",", " ").split()).lower()


def _expanded_search_terms(query: str) -> list[str]:
    compact = re.sub(r"[，。,.;；:：、（）()【】\[\]\"'“”‘’]", " ", query.strip())
    terms = [term.strip() for term in compact.split() if term.strip()]
    if query.strip():
        terms.insert(0, query.strip())
    expanded: list[str] = []
    for term in terms:
        if term and term not in expanded:
            expanded.append(term)
        for key, values in SEARCH_SYNONYMS.items():
            if key in term or term in key:
                for value in values:
                    if value not in expanded:
                        expanded.append(value)
    return expanded


def _fts_match_query(query: str) -> str:
    terms = [term.replace('"', "") for term in _expanded_search_terms(query) if len(term.replace(" ", "")) >= 2]
    return " OR ".join(f'"{term}"' for term in terms[:12])


def _fts_order_ids(db: Session, query: str, search_field: str) -> list[int]:
    if db.get_bind().dialect.name != "sqlite":
        return []
    match_query = _fts_match_query(query)
    if not match_query:
        return []
    try:
        table_exists = db.execute(text("SELECT name FROM sqlite_master WHERE type='table' AND name='work_order_fts'")).first()
        if not table_exists:
            return []
        prefix = f"{search_field} : " if search_field in FTS_COLUMNS else ""
        rows = db.execute(
            text("SELECT rowid FROM work_order_fts WHERE work_order_fts MATCH :query ORDER BY bm25(work_order_fts) LIMIT 5000"),
            {"query": f"{prefix}{match_query}"},
        ).fetchall()
    except Exception:
        return []
    return [int(row[0]) for row in rows]


def _keyword_score(query: str, order: WorkOrder, search_field: str) -> float:
    terms = _expanded_search_terms(query)
    if not terms:
        return 0.0
    if search_field != "all" and search_field in SEARCH_FIELDS:
        fields = [(search_field, _search_text(order, search_field))]
    else:
        fields = [
            ("title", order.title or ""),
            ("problem_category", order.problem_category or ""),
            ("tags", order.tags or ""),
            ("content", order.content or ""),
            ("company_name", order.company_name or ""),
            ("location_point", order.location_point or ""),
            ("order_no", order.order_no or ""),
            ("caller_name", order.caller_name or ""),
            ("caller_phone", order.caller_phone or ""),
            ("host_unit", order.host_unit or ""),
            ("handling_result", order.handling_result or ""),
            ("reply_content", order.reply_content or ""),
            ("extra_fields", order.extra_fields or ""),
        ]
    normalized_query = _normalize_search_text(query)
    score = 0.0
    for field, raw_text in fields:
        normalized_text = _normalize_search_text(raw_text)
        if not normalized_text:
            continue
        weight = SEARCH_FIELD_WEIGHTS.get(field, 1.0)
        if normalized_query and normalized_query in normalized_text:
            score += 2.2 * weight
        for index, term in enumerate(terms):
            normalized_term = _normalize_search_text(term)
            if not normalized_term:
                continue
            count = normalized_text.count(normalized_term)
            if count:
                score += min(count, 4) * weight * (1.0 if index == 0 else 0.65)
    return score


def _semantic_score(query: str, text: str) -> float:
    query = query.strip()
    text = text.strip()
    if not query or not text:
        return 0
    compact_query = _normalize_search_text(query)
    compact_text = _normalize_search_text(text)
    score = 0.0
    if compact_query in compact_text:
        score += 2.0
    if len(compact_query) >= 2:
        query_grams = {compact_query[index : index + 2] for index in range(len(compact_query) - 1)}
        text_grams = {compact_text[index : index + 2] for index in range(max(0, len(compact_text) - 1))}
        if query_grams and text_grams:
            score += len(query_grams & text_grams) / len(query_grams)
    terms = _expanded_search_terms(query)
    if terms:
        matched_terms = [term for term in terms if term and term in text]
        score += min(len(matched_terms), 5) / min(len(terms), 5)
        if matched_terms and compact_query not in compact_text:
            score += 0.6
    score += difflib.SequenceMatcher(None, compact_query[:80], compact_text[:240]).ratio()
    return score


def _order_dict(order: WorkOrder, detail: bool = False) -> dict:
    data = {
        "id": order.id,
        "order_no": order.order_no,
        "order_type": order.order_type,
        "problem_category": order.problem_category,
        "tags": order.tags,
        "title": order.title,
        "status": order.status,
        "caller_name": order.caller_name,
        "caller_phone": order.caller_phone,
        "district": order.district,
        "town": order.town,
        "received_at": order.received_at.isoformat() if order.received_at else None,
        "closed_at": order.closed_at.isoformat() if order.closed_at else None,
        "host_unit": order.host_unit,
        "company_name": order.company_name,
        "is_resolved": order.is_resolved,
        "satisfaction": order.satisfaction,
        "community": order.community,
        "location_point": order.location_point,
        "case_domain": order.case_domain,
        "exported_at": order.exported_at.isoformat() if order.exported_at else None,
        "exported_by": order.exported_by,
        "export_context": order.export_context,
        "created_at": order.created_at.isoformat() if order.created_at else None,
    }
    if detail:
        data.update(
            {
                "content": order.content,
                "handling_result": order.handling_result,
                "reply_content": order.reply_content,
                "handling_method": order.handling_method,
                "order_nature": order.order_nature,
                "batch_id": order.batch_id,
                "extra_fields": _extra_fields(order),
            }
        )
    return data


def _duplicate_event_map(db: Session, order_ids: list[int]) -> dict[int, dict]:
    if not order_ids:
        return {}
    rows = (
        db.query(ClusterMember, EventCluster)
        .join(EventCluster, ClusterMember.cluster_id == EventCluster.id)
        .filter(ClusterMember.work_order_id.in_(order_ids))
        .all()
    )
    result: dict[int, dict] = {}
    for member, cluster in rows:
        result[member.work_order_id] = {
            "cluster_id": cluster.id,
            "title": cluster.title,
            "representative_order_id": cluster.representative_order_id,
            "complaint_count": cluster.complaint_count,
            "match_reason": cluster.match_reason,
        }
    return result


def _duplicate_meta(cluster: EventCluster) -> dict:
    return {
        "cluster_id": cluster.id,
        "title": cluster.title,
        "representative_order_id": cluster.representative_order_id,
        "complaint_count": cluster.complaint_count,
        "match_reason": cluster.match_reason,
    }


def _cluster_rows_for_orders(db: Session, order_ids: list[int]) -> dict[int, EventCluster]:
    if not order_ids:
        return {}
    rows = (
        db.query(ClusterMember, EventCluster)
        .join(EventCluster, ClusterMember.cluster_id == EventCluster.id)
        .filter(ClusterMember.work_order_id.in_(order_ids))
        .all()
    )
    return {member.work_order_id: cluster for member, cluster in rows}


def _decorate_duplicate_item(item: dict, cluster: EventCluster | None, representative: bool = False) -> dict:
    item["duplicate_event"] = _duplicate_meta(cluster) if cluster else None
    item["is_duplicate_representative"] = bool(representative and cluster)
    item["cluster_id"] = cluster.id if cluster else None
    item["cluster_member_count"] = cluster.complaint_count if cluster else 0
    return item


def _collapse_work_orders_by_duplicate_event(db: Session, rows: list[WorkOrder]) -> list[dict]:
    cluster_by_order = _cluster_rows_for_orders(db, [order.id for order in rows])
    seen_clusters: set[int] = set()
    collapsed: list[dict] = []
    for order in rows:
        cluster = cluster_by_order.get(order.id)
        if not cluster:
            collapsed.append(_decorate_duplicate_item(_order_dict(order), None))
            continue
        if cluster.id in seen_clusters:
            continue
        representative = db.get(WorkOrder, cluster.representative_order_id) if cluster.representative_order_id else None
        representative = representative or order
        collapsed.append(_decorate_duplicate_item(_order_dict(representative), cluster, representative=True))
        seen_clusters.add(cluster.id)
    return collapsed


def _collapse_classifications_by_duplicate_event(db: Session, rows: list[tuple[CaseClassification, WorkOrder]]) -> list[dict]:
    cluster_by_order = _cluster_rows_for_orders(db, [order.id for _, order in rows])
    seen_clusters: set[int] = set()
    collapsed: list[dict] = []
    for classification, order in rows:
        cluster = cluster_by_order.get(order.id)
        if not cluster:
            collapsed.append(_decorate_duplicate_item(_classification_dict(classification, order), None))
            continue
        if cluster.id in seen_clusters:
            continue
        representative = db.get(WorkOrder, cluster.representative_order_id) if cluster.representative_order_id else None
        representative = representative or order
        item = _classification_dict(classification, representative)
        item["context_work_order_id"] = order.id
        collapsed.append(_decorate_duplicate_item(item, cluster, representative=True))
        seen_clusters.add(cluster.id)
    return collapsed


def _dedupe_classification_rows(rows: list[tuple[CaseClassification, WorkOrder]]) -> list[tuple[CaseClassification, WorkOrder]]:
    grouped: dict[int, tuple[CaseClassification, WorkOrder]] = {}
    for classification, order in rows:
        existing = grouped.get(order.id)
        if not existing:
            grouped[order.id] = (classification, order)
            continue
        current_key = (
            CLASSIFICATION_MODULE_PRIORITY.get(classification.module, 99),
            -classification.risk_score,
            -(classification.updated_at.timestamp() if classification.updated_at else 0),
        )
        existing_classification = existing[0]
        existing_key = (
            CLASSIFICATION_MODULE_PRIORITY.get(existing_classification.module, 99),
            -existing_classification.risk_score,
            -(existing_classification.updated_at.timestamp() if existing_classification.updated_at else 0),
        )
        if current_key < existing_key:
            grouped[order.id] = (classification, order)
    return sorted(
        grouped.values(),
        key=lambda pair: (
            CLASSIFICATION_MODULE_PRIORITY.get(pair[0].module, 99),
            -pair[0].risk_score,
            -(pair[0].updated_at.timestamp() if pair[0].updated_at else 0),
            pair[1].id,
        ),
    )


@router.post("/auth/login", response_model=LoginResponse)
def login(payload: LoginRequest, request: Request, db: Session = Depends(get_db)) -> LoginResponse:
    user = db.query(User).filter(User.username == payload.username, User.is_active == True).first()  # noqa: E712
    if not user or not verify_password(payload.password, user.password_hash):
        write_audit(db, None, "login_failed", "user", payload.username, "登录失败", request.client.host if request.client else "")
        raise HTTPException(status_code=401, detail="用户名或密码错误")
    write_audit(db, user, "login", "user", str(user.id), "登录系统", request.client.host if request.client else "")
    return LoginResponse(
        token=create_token(user.id),
        username=user.username,
        display_name=user.display_name,
        role=user.role.name,
        permissions=sorted(permissions(user)),
    )


@router.get("/dashboard/summary", response_model=DashboardSummary)
def dashboard(db: Session = Depends(get_db), user: User = Depends(require_permission("read"))):
    domain_rows = (
        db.query(CaseClassification.category, func.count(CaseClassification.id))
        .filter(CaseClassification.module == MODULE_PUBLIC_INTEREST)
        .group_by(CaseClassification.category)
        .order_by(desc(func.count(CaseClassification.id)))
        .limit(8)
        .all()
    )
    town_rows = (
        db.query(WorkOrder.town, func.count(WorkOrder.id))
        .group_by(WorkOrder.town)
        .order_by(desc(func.count(WorkOrder.id)))
        .limit(8)
        .all()
    )
    audits = db.query(AuditLog).order_by(desc(AuditLog.created_at)).limit(8).all()
    has_classifications = db.query(CaseClassification.id).first() is not None
    pending_reviews = (
        db.query(func.count(func.distinct(CaseClassification.work_order_id)))
        .filter(CaseClassification.review_status == "待确认")
        .scalar()
        or 0
    )
    high_risk = (
        db.query(func.count(func.distinct(CaseClassification.work_order_id)))
        .filter(CaseClassification.priority == "高")
        .scalar()
        or 0
    )
    return DashboardSummary(
        work_orders=db.query(WorkOrder).count(),
        clues=db.query(CaseClassification).filter(CaseClassification.module == MODULE_PUBLIC_INTEREST).count() or db.query(Clue).count(),
        pending_reviews=pending_reviews if has_classifications else db.query(Clue).filter(Clue.status == "待确认").count(),
        high_risk=high_risk if has_classifications else db.query(Clue).filter(Clue.priority == "高").count(),
        clusters=db.query(EventCluster).count(),
        unresolved=db.query(WorkOrder).filter(WorkOrder.is_resolved == "未解决").count(),
        domain_distribution=[{"name": name or "未分类", "value": value} for name, value in domain_rows],
        town_distribution=[{"name": name or "未填写", "value": value} for name, value in town_rows],
        recent_audits=[
            {"id": item.id, "username": item.username, "action": item.action, "detail": item.detail, "created_at": item.created_at.isoformat()}
            for item in audits
        ],
    )


@router.get("/imports")
def imports(db: Session = Depends(get_db), user: User = Depends(require_permission("read"))):
    rows = db.query(ImportBatch).order_by(desc(ImportBatch.created_at)).limit(50).all()
    return [
        {
            "id": item.id,
            "filename": item.filename,
            "status": item.status,
            "total_rows": item.total_rows,
            "success_rows": item.success_rows,
            "failed_rows": item.failed_rows,
            "error_message": item.error_message,
            "imported_by": item.imported_by,
            "created_at": item.created_at.isoformat(),
        }
        for item in rows
    ]


@router.post("/imports")
def upload_import(
    request: Request,
    file: UploadFile = File(...),
    db: Session = Depends(get_db),
    user: User = Depends(require_permission("import")),
):
    upload_dir = PROJECT_DIR / "data" / "raw"
    upload_dir.mkdir(parents=True, exist_ok=True)
    suffix = Path(file.filename or "").suffix or ".xlsx"
    target = upload_dir / f"{datetime.utcnow().strftime('%Y%m%d%H%M%S%f')}_{uuid4().hex[:8]}{suffix}"
    with target.open("wb") as fh:
        shutil.copyfileobj(file.file, fh)
    batch = import_workbook(db, target, user.username, original_filename=file.filename)
    rebuild_search_index()
    write_audit(db, user, "import", "import_batch", str(batch.id), f"导入文件 {file.filename}", request.client.host if request.client else "")
    return {
        "id": batch.id,
        "status": batch.status,
        "total_rows": batch.total_rows,
        "success_rows": batch.success_rows,
        "failed_rows": batch.failed_rows,
        "error_message": batch.error_message,
    }


@router.delete("/imports/{batch_id}")
def delete_import(
    batch_id: int,
    request: Request,
    db: Session = Depends(get_db),
    user: User = Depends(require_permission("import")),
):
    batch = db.get(ImportBatch, batch_id)
    if not batch:
        raise HTTPException(status_code=404, detail="导入批次不存在")
    order_ids = [row[0] for row in db.query(WorkOrder.id).filter(WorkOrder.batch_id == batch.id).all()]
    if order_ids:
        db.query(CaseClassification).filter(CaseClassification.work_order_id.in_(order_ids)).delete(synchronize_session=False)
        db.query(ClusterMember).filter(ClusterMember.work_order_id.in_(order_ids)).delete(synchronize_session=False)
        db.query(ClueReview).filter(ClueReview.clue_id.in_(db.query(Clue.id).filter(Clue.work_order_id.in_(order_ids)))).delete(synchronize_session=False)
        db.query(Clue).filter(Clue.work_order_id.in_(order_ids)).delete(synchronize_session=False)
        db.query(WorkOrder).filter(WorkOrder.id.in_(order_ids)).delete(synchronize_session=False)
    db.delete(batch)
    db.commit()
    rebuild_search_index()
    run_screening(db, batch_ids=[], modules=[])
    write_audit(db, user, "delete_import", "import_batch", str(batch_id), f"删除导入批次 {batch.filename}", request.client.host if request.client else "")
    return {"status": "ok", "deleted_orders": len(order_ids)}


@router.get("/work-orders", response_model=PageResponse)
def work_orders(
    page: int = 1,
    page_size: int = 20,
    q: str = "",
    search_field: str = "all",
    search_mode: str = "keyword",
    domain: str = "",
    town: str = "",
    satisfaction: str = "",
    is_resolved: str = "",
    hide_exported: bool = False,
    identify_duplicates: bool = False,
    batch_id: int | None = None,
    db: Session = Depends(get_db),
    user: User = Depends(require_permission("read")),
):
    query = db.query(WorkOrder)
    if batch_id:
        query = query.filter(WorkOrder.batch_id == batch_id)
    if hide_exported:
        query = query.filter(WorkOrder.exported_at.is_(None))
    if domain:
        query = query.filter(WorkOrder.case_domain == domain)
    if town == "__EMPTY__":
        query = query.filter(WorkOrder.town == "")
    elif town:
        query = query.filter(WorkOrder.town == town)
    if satisfaction:
        query = query.filter(WorkOrder.satisfaction == satisfaction)
    if is_resolved:
        query = query.filter(WorkOrder.is_resolved == is_resolved)
    text_search = bool(q)
    semantic_search = bool(q and search_mode == "semantic")
    if text_search:
        fts_ids = _fts_order_ids(db, q, search_field)
        # FTS only indexes a subset of fields. For "all" or non-FTS fields,
        # keep the full filtered candidate set so matches in reply/handling
        # text, caller info, host unit, etc. are not lost.
        candidates_query = query.filter(WorkOrder.id.in_(fts_ids)) if fts_ids and search_field in FTS_COLUMNS else query
        candidates = candidates_query.all()
        scored = [
            (
                item,
                _semantic_score(q, _search_text(item, search_field))
                if semantic_search
                else _keyword_score(q, item, search_field),
            )
            for item in candidates
        ]
        scored = [(item, score) for item, score in scored if score > (0.08 if semantic_search else 0)]
        scored.sort(key=lambda pair: (pair[1], pair[0].closed_at or pair[0].created_at), reverse=True)
        rows = [item for item, _ in scored]
    else:
        rows = query.order_by(desc(WorkOrder.closed_at)).all() if identify_duplicates else []
    if identify_duplicates:
        items = _collapse_work_orders_by_duplicate_event(db, rows)
        total = len(items)
        items = items[(page - 1) * page_size : page * page_size]
    else:
        if text_search:
            total = len(rows)
            rows = rows[(page - 1) * page_size : page * page_size]
        else:
            total = query.count()
            rows = query.order_by(desc(WorkOrder.closed_at)).offset((page - 1) * page_size).limit(page_size).all()
        items = [_decorate_duplicate_item(_order_dict(item), None) for item in rows]
    return PageResponse(total=total, page=page, page_size=page_size, items=items)


@router.get("/work-orders/{order_id}")
def work_order_detail(
    order_id: int,
    request: Request,
    db: Session = Depends(get_db),
    user: User = Depends(require_permission("read")),
):
    order = db.get(WorkOrder, order_id)
    if not order:
        raise HTTPException(status_code=404, detail="工单不存在")
    clue = db.query(Clue).filter(Clue.work_order_id == order.id).first()
    write_audit(db, user, "view_detail", "work_order", str(order.id), "查看工单详情", request.client.host if request.client else "")
    data = _order_dict(order, detail=True)
    data["clue"] = None
    if clue:
        data["clue"] = {
            "id": clue.id,
            "predicted_domain": clue.predicted_domain,
            "priority": clue.priority,
            "risk_score": clue.risk_score,
            "status": clue.status,
            "rule_hits": clue.rule_hits,
            "evidence": clue.evidence,
            "llm_used": clue.llm_used,
            "reviewer": clue.reviewer,
            "review_note": clue.review_note,
            "reviewed_at": clue.reviewed_at.isoformat() if clue.reviewed_at else None,
            "created_at": clue.created_at.isoformat() if clue.created_at else None,
            "updated_at": clue.updated_at.isoformat() if clue.updated_at else None,
        }
    classifications = db.query(CaseClassification).filter(CaseClassification.work_order_id == order.id).all()
    data["classifications"] = [
        {
            "id": item.id,
            "module": item.module,
            "category": item.category,
            "priority": item.priority,
            "risk_score": item.risk_score,
            "review_status": item.review_status,
            "rule_hits": item.rule_hits,
            "evidence": item.evidence,
            "reviewer": item.reviewer,
            "review_note": item.review_note,
            "reviewed_at": item.reviewed_at.isoformat() if item.reviewed_at else None,
            "created_at": item.created_at.isoformat() if item.created_at else None,
            "updated_at": item.updated_at.isoformat() if item.updated_at else None,
        }
        for item in classifications
    ]
    return data


@router.post("/screening/run", response_model=ScreeningRunResponse)
def screening_run(
    payload: ScreeningRunRequest | None = None,
    request: Request = None,
    db: Session = Depends(get_db),
    user: User = Depends(require_permission("screen")),
):
    payload = payload or ScreeningRunRequest()
    result = run_screening(db, batch_ids=payload.batch_ids or None, modules=payload.modules or None)
    write_audit(db, user, "screening_run", "screening", "", str(result), request.client.host if request.client else "")
    return ScreeningRunResponse(message="筛查完成", **result)


@router.get("/clues", response_model=PageResponse)
def clues(
    page: int = 1,
    page_size: int = 20,
    status: str = "",
    priority: str = "",
    domain: str = "",
    db: Session = Depends(get_db),
    user: User = Depends(require_permission("read")),
):
    query = db.query(Clue, WorkOrder).join(WorkOrder, Clue.work_order_id == WorkOrder.id)
    if status:
        query = query.filter(Clue.status == status)
    if priority:
        query = query.filter(Clue.priority == priority)
    if domain == "__EMPTY__":
        query = query.filter(Clue.predicted_domain == "")
    elif domain:
        query = query.filter(Clue.predicted_domain == domain)
    total = query.count()
    rows = query.order_by(desc(Clue.risk_score)).offset((page - 1) * page_size).limit(page_size).all()
    items = []
    for clue, order in rows:
        items.append(
            {
                "id": clue.id,
                "work_order_id": order.id,
                "order_no": order.order_no,
                "title": order.title,
                "problem_category": order.problem_category,
                "town": order.town,
                "location_point": order.location_point,
                "predicted_domain": clue.predicted_domain,
                "priority": clue.priority,
                "risk_score": clue.risk_score,
                "status": clue.status,
                "rule_hits": clue.rule_hits,
                "evidence": clue.evidence,
                "is_resolved": order.is_resolved,
                "satisfaction": order.satisfaction,
            }
        )
    return PageResponse(total=total, page=page, page_size=page_size, items=items)


@router.patch("/clues/{clue_id}/review")
def review_clue(
    clue_id: int,
    payload: ClueReviewRequest,
    request: Request,
    db: Session = Depends(get_db),
    user: User = Depends(require_permission("review")),
):
    clue = db.get(Clue, clue_id)
    if not clue:
        raise HTTPException(status_code=404, detail="线索不存在")
    before_status = clue.status
    before_domain = clue.predicted_domain
    clue.status = payload.review_status or payload.status or "已确认"
    if payload.predicted_domain is not None:
        clue.predicted_domain = payload.predicted_domain.strip() or "未知领域"
    if payload.priority:
        clue.priority = payload.priority
    clue.review_note = payload.note
    clue.reviewer = user.username
    clue.reviewed_at = datetime.utcnow()
    clue.updated_at = datetime.utcnow()
    if clue.work_order:
        clue.work_order.case_domain = clue.predicted_domain
    db.add(
        ClueReview(
            clue_id=clue.id,
            reviewer=user.username,
            before_status=before_status,
            after_status=clue.status,
            before_domain=before_domain,
            after_domain=clue.predicted_domain,
            note=payload.note,
        )
    )
    db.commit()
    write_audit(db, user, "review_clue", "clue", str(clue.id), payload.note, request.client.host if request.client else "")
    return {"status": "ok"}


def _classification_dict(item: CaseClassification, order: WorkOrder) -> dict:
    return {
        "id": item.id,
        "work_order_id": order.id,
        "order_no": order.order_no,
        "title": order.title,
        "problem_category": order.problem_category,
        "town": order.town,
        "location_point": order.location_point,
        "company_name": order.company_name,
        "module": item.module,
        "category": item.category,
        "priority": item.priority,
        "risk_score": item.risk_score,
        "review_status": item.review_status,
        "rule_hits": item.rule_hits,
        "evidence": item.evidence,
        "is_resolved": order.is_resolved,
        "satisfaction": order.satisfaction,
        "exported_at": order.exported_at.isoformat() if order.exported_at else None,
        "exported_by": order.exported_by,
        "export_context": order.export_context,
    }


@router.get("/classifications", response_model=PageResponse)
def classifications(
    page: int = 1,
    page_size: int = 50,
    module: str = MODULE_PUBLIC_INTEREST,
    category: str = "",
    review_status: str = "",
    priority: str = "",
    hide_exported: bool = False,
    identify_duplicates: bool = False,
    dedupe_work_orders: bool = False,
    db: Session = Depends(get_db),
    user: User = Depends(require_permission("read")),
):
    query = db.query(CaseClassification, WorkOrder).join(WorkOrder, CaseClassification.work_order_id == WorkOrder.id)
    if module:
        query = query.filter(CaseClassification.module == module)
    if category == "__EMPTY__":
        query = query.filter(CaseClassification.category == "")
    elif category:
        query = query.filter(CaseClassification.category == category)
    if review_status:
        query = query.filter(CaseClassification.review_status == review_status)
    if priority:
        query = query.filter(CaseClassification.priority == priority)
    if hide_exported:
        query = query.filter(WorkOrder.exported_at.is_(None))
    ordered_query = query.order_by(desc(CaseClassification.risk_score), desc(CaseClassification.updated_at))
    if identify_duplicates:
        rows = ordered_query.all()
        if dedupe_work_orders:
            rows = _dedupe_classification_rows(rows)
        items = _collapse_classifications_by_duplicate_event(db, rows)
        total = len(items)
        items = items[(page - 1) * page_size : page * page_size]
        return PageResponse(total=total, page=page, page_size=page_size, items=items)
    if dedupe_work_orders:
        rows = _dedupe_classification_rows(ordered_query.all())
        total = len(rows)
        rows = rows[(page - 1) * page_size : page * page_size]
    else:
        total = query.count()
        rows = ordered_query.offset((page - 1) * page_size).limit(page_size).all()
    items = [_classification_dict(item, order) for item, order in rows]
    return PageResponse(total=total, page=page, page_size=page_size, items=items)


@router.get("/classification-categories")
def classification_categories(
    module: str = MODULE_PUBLIC_INTEREST,
    hide_exported: bool = False,
    db: Session = Depends(get_db),
    user: User = Depends(require_permission("read")),
):
    query = db.query(CaseClassification.category, func.count(CaseClassification.id)).join(WorkOrder, CaseClassification.work_order_id == WorkOrder.id)
    if module:
        query = query.filter(CaseClassification.module == module)
    if hide_exported:
        query = query.filter(WorkOrder.exported_at.is_(None))
    rows = query.group_by(CaseClassification.category).order_by(desc(func.count(CaseClassification.id))).all()
    rule_rows = db.query(ScreeningRule.domain).filter(ScreeningRule.module == module).all()
    counts = {name or "未分类": value for name, value in rows}
    for (domain,) in rule_rows:
        counts.setdefault(domain or "未分类", 0)
    if module in {MODULE_VULNERABLE, MODULE_ADMINISTRATIVE}:
        counts.setdefault("其他", 0)
    else:
        counts.setdefault("未知领域", 0)
    return [{"name": name, "value": value} for name, value in sorted(counts.items(), key=lambda item: (-item[1], item[0]))]


def _cluster_member_order_ids(db: Session, work_order_id: int) -> list[int]:
    member = db.query(ClusterMember).filter(ClusterMember.work_order_id == work_order_id).first()
    if not member:
        return [work_order_id]
    return [row[0] for row in db.query(ClusterMember.work_order_id).filter(ClusterMember.cluster_id == member.cluster_id).all()]


def _review_classification_rows(
    db: Session,
    items: list[CaseClassification],
    *,
    category: str,
    status: str,
    priority: str | None,
    note: str,
    reviewer: str,
    apply_to_cluster: bool,
) -> int:
    expanded: dict[int, CaseClassification] = {}
    for item in items:
        targets = [item]
        if apply_to_cluster:
            order_ids = _cluster_member_order_ids(db, item.work_order_id)
            targets = (
                db.query(CaseClassification)
                .filter(CaseClassification.module == item.module, CaseClassification.work_order_id.in_(order_ids))
                .all()
            )
        for target in targets:
            expanded[target.id] = target

    now = datetime.utcnow()
    for target in expanded.values():
        target.category = category
        target.review_status = status
        if priority:
            target.priority = priority
        target.review_note = note
        target.reviewer = reviewer
        target.reviewed_at = now
        target.updated_at = now
        if target.module == MODULE_PUBLIC_INTEREST and target.work_order:
            target.work_order.case_domain = target.category
            clue = db.query(Clue).filter(Clue.work_order_id == target.work_order_id).first()
            if clue:
                clue.predicted_domain = target.category
                clue.status = target.review_status
                clue.priority = target.priority
                clue.review_note = target.review_note
                clue.reviewer = target.reviewer
                clue.reviewed_at = target.reviewed_at
                clue.updated_at = target.updated_at
    return len(expanded)


@router.patch("/classifications/batch-review")
def batch_review_classifications(
    payload: ClassificationBatchReviewRequest,
    request: Request,
    db: Session = Depends(get_db),
    user: User = Depends(require_permission("review")),
):
    category = (payload.category or "").strip()
    if not category:
        raise HTTPException(status_code=400, detail="分类不能为空")
    items = db.query(CaseClassification).filter(CaseClassification.id.in_(payload.classification_ids)).all()
    if not items:
        raise HTTPException(status_code=404, detail="未找到可确认的分类结果")
    count = _review_classification_rows(
        db,
        items,
        category=category,
        status="已确认",
        priority=None,
        note=payload.note,
        reviewer=user.username,
        apply_to_cluster=payload.apply_to_cluster,
    )
    db.commit()
    write_audit(db, user, "batch_review_classification", "case_classification", ",".join(map(str, payload.classification_ids)), f"{category} · {count}条", request.client.host if request.client else "")
    return {"status": "ok", "updated": count}


@router.patch("/classifications/{classification_id}/review")
def review_classification(
    classification_id: int,
    payload: ClueReviewRequest,
    request: Request,
    db: Session = Depends(get_db),
    user: User = Depends(require_permission("review")),
):
    item = db.get(CaseClassification, classification_id)
    if not item:
        raise HTTPException(status_code=404, detail="分类结果不存在")
    category = (payload.predicted_domain or item.category or "未知领域").strip()
    status = payload.review_status or payload.status or "已确认"
    count = _review_classification_rows(
        db,
        [item],
        category=category,
        status=status,
        priority=payload.priority,
        note=payload.note,
        reviewer=user.username,
        apply_to_cluster=payload.apply_to_cluster,
    )
    db.commit()
    write_audit(db, user, "review_classification", "case_classification", str(item.id), f"{payload.note} · 更新{count}条", request.client.host if request.client else "")
    return {"status": "ok", "updated": count}


@router.get("/clusters", response_model=PageResponse)
def clusters(page: int = 1, page_size: int = 20, risk: str = "", db: Session = Depends(get_db), user: User = Depends(require_permission("read"))):
    query = db.query(EventCluster)
    if risk:
        query = query.filter(EventCluster.risk_level == risk)
    total = query.count()
    rows = query.order_by(desc(EventCluster.complaint_count)).offset((page - 1) * page_size).limit(page_size).all()
    return PageResponse(
        total=total,
        page=page,
        page_size=page_size,
        items=[cluster_dict_with_assessment(db, item) for item in rows],
    )


@router.get("/clusters/{cluster_id}")
def cluster_detail(cluster_id: int, db: Session = Depends(get_db), user: User = Depends(require_permission("read"))):
    cluster = db.get(EventCluster, cluster_id)
    if not cluster:
        raise HTTPException(status_code=404, detail="屡诉未决事件不存在")
    member_rows = (
        db.query(ClusterMember, WorkOrder)
        .join(WorkOrder, ClusterMember.work_order_id == WorkOrder.id)
        .filter(ClusterMember.cluster_id == cluster.id)
        .order_by(desc(WorkOrder.closed_at))
        .all()
    )
    representative = db.get(WorkOrder, cluster.representative_order_id) if cluster.representative_order_id else None
    if not representative and member_rows:
        representative = member_rows[0][1]
    assessment = cluster_intervention_assessment(db, cluster)
    return {
        "id": cluster.id,
        "cluster_key": cluster.cluster_key,
        "title": cluster.title,
        "location_point": cluster.location_point,
        "town": cluster.town,
        "complaint_count": cluster.complaint_count,
        "unresolved_count": cluster.unresolved_count,
        "dissatisfied_count": cluster.dissatisfied_count,
        "risk_level": cluster.risk_level,
        "representative_order_id": cluster.representative_order_id,
        "representative_order": _order_dict(representative, detail=True) if representative else None,
        "match_reason": cluster.match_reason,
        "first_seen_at": cluster.first_seen_at.isoformat() if cluster.first_seen_at else None,
        "last_seen_at": cluster.last_seen_at.isoformat() if cluster.last_seen_at else None,
        "created_at": cluster.created_at.isoformat() if cluster.created_at else None,
        **assessment,
        "members": [_order_dict(order, detail=True) for _, order in member_rows],
    }


@router.get("/audit-logs")
def audit_logs(db: Session = Depends(get_db), user: User = Depends(require_permission("audit"))):
    rows = db.query(AuditLog).order_by(desc(AuditLog.created_at)).limit(200).all()
    return [
        {
            "id": item.id,
            "username": item.username,
            "action": item.action,
            "target_type": item.target_type,
            "target_id": item.target_id,
            "detail": item.detail,
            "ip_address": item.ip_address,
            "created_at": item.created_at.isoformat(),
        }
        for item in rows
    ]


@router.get("/rules")
def rules(module: str = "", db: Session = Depends(get_db), user: User = Depends(require_permission("read"))):
    query = db.query(ScreeningRule)
    if module:
        query = query.filter(ScreeningRule.module == module)
    return [
        {"id": item.id, "name": item.name, "module": item.module, "domain": item.domain, "keywords": item.keywords, "weight": item.weight, "enabled": item.enabled}
        for item in query.order_by(ScreeningRule.module.asc(), ScreeningRule.domain.asc(), ScreeningRule.id.asc()).all()
    ]


def _normalize_rule_payload(payload: RuleCreateRequest | RuleUpdateRequest) -> dict:
    name = payload.name.strip()
    domain = payload.domain.strip()
    keywords = ",".join([item.strip() for item in payload.keywords.replace("，", ",").split(",") if item.strip()])
    if not name or not domain or not keywords:
        raise HTTPException(status_code=400, detail="规则名称、领域、关键词均不能为空")
    module = (payload.module or MODULE_PUBLIC_INTEREST).strip() or MODULE_PUBLIC_INTEREST
    if module not in RULE_MODULES:
        raise HTTPException(status_code=400, detail="线索标注仅支持公益成案领域、弱势群体、行政违法")
    return {"name": name, "module": module, "domain": domain, "keywords": keywords, "weight": payload.weight, "enabled": payload.enabled}


@router.post("/rules")
def create_rule(
    payload: RuleCreateRequest,
    request: Request,
    db: Session = Depends(get_db),
    user: User = Depends(require_permission("screen")),
):
    data = _normalize_rule_payload(payload)
    if db.query(ScreeningRule).filter(ScreeningRule.name == data["name"]).first():
        raise HTTPException(status_code=400, detail="规则名称已存在")
    rule = ScreeningRule(**data)
    db.add(rule)
    db.commit()
    db.refresh(rule)
    write_audit(db, user, "create_rule", "screening_rule", str(rule.id), f"新增规则：{rule.name}", request.client.host if request.client else "")
    return {"id": rule.id, "name": rule.name, "module": rule.module, "domain": rule.domain, "keywords": rule.keywords, "weight": rule.weight, "enabled": rule.enabled}


@router.put("/rules/{rule_id}")
def update_rule(
    rule_id: int,
    payload: RuleUpdateRequest,
    request: Request,
    db: Session = Depends(get_db),
    user: User = Depends(require_permission("screen")),
):
    rule = db.get(ScreeningRule, rule_id)
    if not rule:
        raise HTTPException(status_code=404, detail="规则不存在")
    data = _normalize_rule_payload(payload)
    duplicate = db.query(ScreeningRule).filter(ScreeningRule.name == data["name"], ScreeningRule.id != rule_id).first()
    if duplicate:
        raise HTTPException(status_code=400, detail="规则名称已存在")
    for key, value in data.items():
        setattr(rule, key, value)
    db.commit()
    db.refresh(rule)
    write_audit(db, user, "update_rule", "screening_rule", str(rule.id), f"编辑规则：{rule.name}", request.client.host if request.client else "")
    return {"id": rule.id, "name": rule.name, "module": rule.module, "domain": rule.domain, "keywords": rule.keywords, "weight": rule.weight, "enabled": rule.enabled}


@router.delete("/rules/{rule_id}")
def delete_rule(
    rule_id: int,
    request: Request,
    db: Session = Depends(get_db),
    user: User = Depends(require_permission("screen")),
):
    rule = db.get(ScreeningRule, rule_id)
    if not rule:
        raise HTTPException(status_code=404, detail="规则不存在")
    rule_name = rule.name
    db.delete(rule)
    db.commit()
    write_audit(db, user, "delete_rule", "screening_rule", str(rule_id), f"删除规则：{rule_name}", request.client.host if request.client else "")
    return {"status": "ok"}


@router.get("/rules/{rule_id}/matches", response_model=PageResponse)
def rule_matches(
    rule_id: int,
    page: int = 1,
    page_size: int = 50,
    db: Session = Depends(get_db),
    user: User = Depends(require_permission("read")),
):
    rule = db.get(ScreeningRule, rule_id)
    if not rule:
        raise HTTPException(status_code=404, detail="规则不存在")
    keywords = [item.strip() for item in rule.keywords.split(",") if item.strip()]
    if not keywords:
        return PageResponse(total=0, page=page, page_size=page_size, items=[])

    filters = []
    for keyword in keywords:
        like = f"%{keyword}%"
        filters.extend(
            [
                WorkOrder.problem_category.like(like),
                WorkOrder.tags.like(like),
                WorkOrder.title.like(like),
                WorkOrder.content.like(like),
                WorkOrder.handling_result.like(like),
                WorkOrder.reply_content.like(like),
                WorkOrder.host_unit.like(like),
                WorkOrder.company_name.like(like),
                WorkOrder.location_point.like(like),
                WorkOrder.extra_fields.like(like),
            ]
        )
    query = db.query(WorkOrder).filter(or_(*filters))
    total = query.count()
    rows = query.order_by(desc(WorkOrder.closed_at)).offset((page - 1) * page_size).limit(page_size).all()
    items = []
    for order in rows:
        source_text = " ".join(
            [
                order.problem_category or "",
                order.tags or "",
                order.title or "",
                order.content or "",
                order.handling_result or "",
                order.reply_content or "",
                order.host_unit or "",
                order.company_name or "",
                order.location_point or "",
                order.extra_fields or "",
            ]
        )
        data = _order_dict(order, detail=False)
        data["matched_keywords"] = [keyword for keyword in keywords if keyword in source_text]
        items.append(data)
    return PageResponse(total=total, page=page, page_size=page_size, items=items)


@router.get("/llm-config")
def get_llm_config(db: Session = Depends(get_db), user: User = Depends(require_permission("admin"))):
    cfg = db.query(LLMConfig).first()
    if not cfg:
        return {"provider": "openai-compatible", "base_url": "", "model": "", "api_key_masked": "", "enabled": False}
    return {"provider": cfg.provider, "base_url": cfg.base_url, "model": cfg.model, "api_key_masked": cfg.api_key_masked, "enabled": cfg.enabled}


@router.post("/llm-config")
def save_llm_config(payload: LLMConfigRequest, request: Request, db: Session = Depends(get_db), user: User = Depends(require_permission("admin"))):
    cfg = db.query(LLMConfig).first()
    masked = f"{payload.api_key[:4]}****{payload.api_key[-4:]}" if payload.api_key else ""
    if not cfg:
        cfg = LLMConfig()
        db.add(cfg)
    cfg.provider = payload.provider
    cfg.base_url = payload.base_url
    cfg.model = payload.model
    cfg.api_key_masked = masked
    cfg.enabled = payload.enabled
    db.commit()
    write_audit(db, user, "save_llm_config", "llm_config", str(cfg.id), "更新大模型配置", request.client.host if request.client else "")
    return {"status": "ok"}


@router.get("/performance/anomalies")
def performance_anomaly_api(
    dimension: str = "host_unit",
    period: str = "month",
    db: Session = Depends(get_db),
    user: User = Depends(require_permission("read")),
):
    if dimension not in {"host_unit", "town", "category"}:
        dimension = "host_unit"
    if period not in {"week", "month", "quarter"}:
        period = "month"
    return performance_anomalies(db, dimension, period)


@router.get("/trends")
def trends_api(
    period: str = "month",
    group_by: str = "category",
    db: Session = Depends(get_db),
    user: User = Depends(require_permission("read")),
):
    if period not in {"week", "month", "quarter"}:
        period = "month"
    if group_by not in {"category", "problem_category", "town"}:
        group_by = "category"
    return trend_analysis(db, period, group_by)


@router.post("/exports")
def exports(payload: ExportRequest, request: Request, db: Session = Depends(get_db), user: User = Depends(require_permission("export"))):
    task = create_export(db, payload.export_type, user.username)
    write_audit(db, user, "export", "export_task", str(task.id), payload.export_type, request.client.host if request.client else "")
    return {"id": task.id, "status": task.status, "file_path": Path(task.file_path).name}


@router.post("/exports/selected")
def selected_export(
    payload: SelectedExportRequest,
    request: Request,
    db: Session = Depends(get_db),
    user: User = Depends(require_permission("export")),
):
    task = create_selected_export(
        db,
        payload.export_type,
        user.username,
        payload.work_order_ids,
        payload.cluster_ids,
        payload.representative_work_order_ids,
        payload.duplicate_export_scope,
        payload.module,
        payload.category,
        payload.identify_duplicates,
        payload.hide_exported,
    )
    write_audit(db, user, "export_selected", "export_task", str(task.id), str(payload.model_dump()), request.client.host if request.client else "")
    return {"id": task.id, "status": task.status, "file_path": Path(task.file_path).name}


@router.get("/exports")
def list_exports(db: Session = Depends(get_db), user: User = Depends(require_permission("export"))):
    rows = db.query(ExportTask).order_by(desc(ExportTask.created_at)).limit(80).all()
    return [
        {
            "id": item.id,
            "export_type": item.export_type,
            "status": item.status,
            "file_path": Path(item.file_path).name if item.file_path else "",
            "created_by": item.created_by,
            "created_at": item.created_at.isoformat(),
        }
        for item in rows
    ]


@router.get("/exports/{task_id}/download")
def download_export(task_id: int, db: Session = Depends(get_db), user: User = Depends(require_permission("export"))):
    task = db.get(ExportTask, task_id)
    if not task or not task.file_path or not Path(task.file_path).exists():
        raise HTTPException(status_code=404, detail="导出文件不存在")
    return FileResponse(task.file_path, filename=Path(task.file_path).name)


@router.get("/health")
def health():
    return {"status": "ok", "app": settings.app_name}
