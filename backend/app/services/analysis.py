from __future__ import annotations

from collections import defaultdict
from datetime import datetime, timedelta

from sqlalchemy.orm import Session

from app.models.entities import CaseClassification, ClusterMember, EventCluster, WorkOrder
from app.services.rules import MODULE_PUBLIC_INTEREST


HIGH_RISK_PUBLIC_INTEREST = {
    "生态环境和资源保护",
    "食品药品安全",
    "安全生产",
    "个人信息保护",
    "反电信网络诈骗",
    "农产品质量安全",
    "野生动物保护",
}

ADVICE_ORDER = {
    "暂不建议": 0,
    "建议关注": 1,
    "建议初查": 2,
    "建议立即介入": 3,
}


def event_time(order: WorkOrder) -> datetime:
    return order.received_at or order.closed_at or order.created_at or datetime.utcnow()


def is_unresolved(order: WorkOrder) -> bool:
    value = (order.is_resolved or "").strip()
    if not value:
        return False
    return "未" in value or "否" in value or "不" in value


def is_dissatisfied(order: WorkOrder) -> bool:
    return "不满意" in (order.satisfaction or "")


def has_response(order: WorkOrder) -> bool:
    return bool((order.handling_result or "").strip() or (order.reply_content or "").strip())


def cluster_members(db: Session, cluster_id: int) -> list[WorkOrder]:
    return [
        order
        for _, order in (
            db.query(ClusterMember, WorkOrder)
            .join(WorkOrder, ClusterMember.work_order_id == WorkOrder.id)
            .filter(ClusterMember.cluster_id == cluster_id)
            .all()
        )
    ]


def _public_interest_categories(db: Session, work_order_ids: list[int]) -> list[str]:
    if not work_order_ids:
        return []
    rows = (
        db.query(CaseClassification.category)
        .filter(
            CaseClassification.work_order_id.in_(work_order_ids),
            CaseClassification.module == MODULE_PUBLIC_INTEREST,
        )
        .all()
    )
    return sorted({category for (category,) in rows if category})


def _has_high_risk_public_interest(db: Session, work_order_ids: list[int]) -> bool:
    if not work_order_ids:
        return False
    rows = (
        db.query(CaseClassification)
        .filter(
            CaseClassification.work_order_id.in_(work_order_ids),
            CaseClassification.module == MODULE_PUBLIC_INTEREST,
        )
        .all()
    )
    return any(item.priority == "高" or item.category in HIGH_RISK_PUBLIC_INTEREST for item in rows)


def cluster_intervention_assessment(db: Session, cluster: EventCluster) -> dict:
    members = cluster_members(db, cluster.id)
    if members:
        times = sorted(event_time(order) for order in members)
        duration_days = max((times[-1] - times[0]).days, 0)
        unresolved_count = sum(1 for order in members if is_unresolved(order))
        dissatisfied_count = sum(1 for order in members if is_dissatisfied(order))
        work_order_ids = [order.id for order in members]
    else:
        duration_days = 0
        unresolved_count = cluster.unresolved_count
        dissatisfied_count = cluster.dissatisfied_count
        work_order_ids = []
    complaint_count = cluster.complaint_count or len(members)
    categories = _public_interest_categories(db, work_order_ids)
    high_risk = _has_high_risk_public_interest(db, work_order_ids)

    severity = "一般"
    advice = "暂不建议"
    if (complaint_count >= 10 or duration_days >= 90) and (unresolved_count > 0 or high_risk):
        severity = "紧急"
        advice = "建议立即介入"
    elif (complaint_count >= 5 or duration_days >= 60) and (unresolved_count > 0 or dissatisfied_count > 0):
        severity = "重点"
        advice = "建议初查"
    elif (complaint_count >= 3 or duration_days >= 30) and unresolved_count > 0:
        severity = "一般"
        advice = "建议关注"

    representative = db.get(WorkOrder, cluster.representative_order_id) if cluster.representative_order_id else None
    category_text = "、".join(categories) if categories else "未匹配公益成案领域"
    reason = (
        f"反映次数{complaint_count}次，持续{duration_days}天，未解决{unresolved_count}次，"
        f"不满意{dissatisfied_count}次，涉及领域：{category_text}，"
        f"代表事件：{representative.order_no if representative else cluster.representative_order_id or '未设置'}。"
    )
    if high_risk:
        reason += "存在高风险公益成案领域或高风险分类结果。"
    return {
        "duration_days": duration_days,
        "severity_level": severity,
        "intervention_advice": advice,
        "assessment_reason": reason,
        "public_interest_categories": categories,
    }


def cluster_dict_with_assessment(db: Session, cluster: EventCluster) -> dict:
    assessment = cluster_intervention_assessment(db, cluster)
    return {
        "id": cluster.id,
        "title": cluster.title,
        "location_point": cluster.location_point,
        "town": cluster.town,
        "complaint_count": cluster.complaint_count,
        "unresolved_count": cluster.unresolved_count,
        "dissatisfied_count": cluster.dissatisfied_count,
        "risk_level": cluster.risk_level,
        "representative_order_id": cluster.representative_order_id,
        "match_reason": cluster.match_reason,
        "first_seen_at": cluster.first_seen_at.isoformat() if cluster.first_seen_at else None,
        "last_seen_at": cluster.last_seen_at.isoformat() if cluster.last_seen_at else None,
        **assessment,
    }


def _period_start(value: datetime, period: str) -> datetime:
    if period == "week":
        start = value - timedelta(days=value.weekday())
        return datetime(start.year, start.month, start.day)
    if period == "quarter":
        month = ((value.month - 1) // 3) * 3 + 1
        return datetime(value.year, month, 1)
    return datetime(value.year, value.month, 1)


def _period_label(value: datetime, period: str) -> str:
    start = _period_start(value, period)
    if period == "week":
        year, week, _ = start.isocalendar()
        return f"{year}-W{week:02d}"
    if period == "quarter":
        return f"{start.year}Q{((start.month - 1) // 3) + 1}"
    return start.strftime("%Y-%m")


def _previous_period_start(start: datetime, period: str) -> datetime:
    if period == "week":
        return start - timedelta(days=7)
    if period == "quarter":
        month = start.month - 3
        year = start.year
        if month <= 0:
            month += 12
            year -= 1
        return datetime(year, month, 1)
    month = start.month - 1
    year = start.year
    if month <= 0:
        month = 12
        year -= 1
    return datetime(year, month, 1)


def _dimension_value(order: WorkOrder, classification: CaseClassification | None, dimension: str) -> str:
    if dimension == "town":
        return order.town or "未填写街乡镇"
    if dimension == "category":
        return classification.category if classification else (order.case_domain or "未知领域")
    return order.host_unit or order.town or "未填写主办单位"


def _cluster_dimension_values(
    db: Session,
    cluster: EventCluster,
    classifications: dict[int, CaseClassification],
    dimension: str,
) -> set[str]:
    values = set()
    for order in cluster_members(db, cluster.id):
        values.add(_dimension_value(order, classifications.get(order.id), dimension))
    return values


def _best_cluster_assessment(db: Session, name: str, dimension: str, classifications: dict[int, CaseClassification]) -> dict:
    best: dict | None = None
    for cluster in db.query(EventCluster).all():
        if name not in _cluster_dimension_values(db, cluster, classifications, dimension):
            continue
        assessment = cluster_intervention_assessment(db, cluster)
        score = ADVICE_ORDER.get(assessment["intervention_advice"], 0)
        if best is None or score > ADVICE_ORDER.get(best["intervention_advice"], 0):
            best = {**assessment, "representative_event": cluster.title, "cluster_id": cluster.id}
    return best or {
        "severity_level": "一般",
        "intervention_advice": "暂不建议",
        "assessment_reason": "未发现同时满足长期存在、多次反映、仍未解决三要素的屡诉未决事件。",
        "representative_event": "",
        "cluster_id": None,
    }


def performance_anomalies(db: Session, dimension: str = "host_unit", period: str = "month") -> list[dict]:
    orders = db.query(WorkOrder).all()
    if not orders:
        return []
    latest_time = max(event_time(order) for order in orders)
    current_start = _period_start(latest_time, period)
    previous_start = _previous_period_start(current_start, period)
    classifications = {
        item.work_order_id: item
        for item in db.query(CaseClassification).filter(CaseClassification.module == MODULE_PUBLIC_INTEREST).all()
    }

    buckets: dict[tuple[str, str], list[WorkOrder]] = defaultdict(list)
    for order in orders:
        order_time = event_time(order)
        if order_time >= current_start:
            bucket = "current"
        elif order_time >= previous_start:
            bucket = "previous"
        else:
            continue
        value = _dimension_value(order, classifications.get(order.id), dimension)
        buckets[(value, bucket)].append(order)

    names = sorted({name for name, _ in buckets})
    rows: list[dict] = []
    for name in names:
        current = buckets.get((name, "current"), [])
        previous = buckets.get((name, "previous"), [])
        if not current:
            continue

        def rate(items: list[WorkOrder], predicate) -> float:
            return round(sum(1 for item in items if predicate(item)) / len(items), 4) if items else 0.0

        solve_rate = rate(current, lambda item: not is_unresolved(item))
        satisfaction_rate = rate(current, lambda item: not is_dissatisfied(item))
        response_rate = rate(current, has_response)
        previous_satisfaction = rate(previous, lambda item: not is_dissatisfied(item))
        reasons = []
        if len(current) >= 2 and solve_rate < 0.6:
            reasons.append("解决率偏低")
        if len(current) >= 2 and satisfaction_rate < 0.6:
            reasons.append("满意率偏低")
        if len(current) >= 2 and response_rate < 0.7:
            reasons.append("响应率偏低")
        if previous and previous_satisfaction - satisfaction_rate >= 0.25:
            reasons.append("满意率较上一周期明显下降")
        assessment = _best_cluster_assessment(db, name, dimension, classifications)
        if reasons and assessment["intervention_advice"] == "暂不建议":
            assessment = {
                **assessment,
                "intervention_advice": "建议关注",
                "assessment_reason": f"{'、'.join(reasons)}。{assessment['assessment_reason']}",
            }
        rows.append(
            {
                "name": name,
                "dimension": dimension,
                "period": period,
                "total": len(current),
                "previous_total": len(previous),
                "resolved": sum(1 for item in current if not is_unresolved(item)),
                "unresolved": sum(1 for item in current if is_unresolved(item)),
                "dissatisfied": sum(1 for item in current if is_dissatisfied(item)),
                "responded": sum(1 for item in current if has_response(item)),
                "solve_rate": round(solve_rate * 100, 1),
                "satisfaction_rate": round(satisfaction_rate * 100, 1),
                "response_rate": round(response_rate * 100, 1),
                "anomaly": "、".join(reasons),
                **assessment,
            }
        )
    return sorted(rows, key=lambda item: (ADVICE_ORDER.get(item["intervention_advice"], 0), bool(item["anomaly"]), item["total"]), reverse=True)


def trend_analysis(db: Session, period: str = "month", group_by: str = "category") -> list[dict]:
    if group_by == "category":
        rows = (
            db.query(CaseClassification, WorkOrder)
            .join(WorkOrder, CaseClassification.work_order_id == WorkOrder.id)
            .filter(CaseClassification.module == MODULE_PUBLIC_INTEREST)
            .all()
        )
        pairs = [(classification.category or "未知领域", order) for classification, order in rows]
    else:
        pairs = []
        for order in db.query(WorkOrder).all():
            if group_by == "town":
                pairs.append((order.town or "未填写街乡镇", order))
            else:
                pairs.append((order.problem_category or "未填写问题分类", order))
    series: dict[str, dict[str, int]] = defaultdict(lambda: defaultdict(int))
    for name, order in pairs:
        series[name][_period_label(event_time(order), period)] += 1
    all_periods = sorted({label for values in series.values() for label in values})
    if not all_periods:
        return []
    latest = all_periods[-1]
    previous = all_periods[-2] if len(all_periods) >= 2 else ""
    result = []
    for name, values in series.items():
        latest_count = values.get(latest, 0)
        previous_count = values.get(previous, 0) if previous else 0
        if previous_count == 0:
            change_rate = 100.0 if latest_count else 0.0
        else:
            change_rate = round((latest_count - previous_count) / previous_count * 100, 1)
        tag = "平稳"
        if previous_count == 0 and latest_count >= 2:
            tag = "新兴问题"
        if latest_count >= 5:
            tag = "阶段性高发"
        elif previous_count and latest_count - previous_count >= 2 and latest_count / previous_count >= 1.5:
            tag = "明显上升"
        result.append(
            {
                "name": name,
                "group_by": group_by,
                "period": period,
                "latest_period": latest,
                "latest_count": latest_count,
                "previous_period": previous,
                "previous_count": previous_count,
                "change_rate": change_rate,
                "tag": tag,
                "series": [{"period": label, "count": values.get(label, 0)} for label in all_periods],
            }
        )
    return sorted(result, key=lambda item: (item["tag"] != "平稳", item["latest_count"], item["change_rate"]), reverse=True)
