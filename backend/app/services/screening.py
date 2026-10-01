from __future__ import annotations

import difflib
import json
import re
from collections import defaultdict
from datetime import datetime

from sqlalchemy.orm import Session

from app.models.entities import CaseClassification, Clue, ClusterMember, EventCluster, ScreeningRule, WorkOrder
from app.services.rules import (
    ADMINISTRATIVE_UNKNOWN,
    DEFAULT_RULES,
    MODULE_ADMINISTRATIVE,
    MODULE_PUBLIC_INTEREST,
    MODULE_VULNERABLE,
    PUBLIC_INTEREST_TERMS,
    PUBLIC_INTEREST_UNKNOWN,
    VULNERABLE_UNKNOWN,
)


UNKNOWN_DOMAIN = PUBLIC_INTEREST_UNKNOWN
SUPPORTED_MODULES = {MODULE_PUBLIC_INTEREST, MODULE_VULNERABLE, MODULE_ADMINISTRATIVE}
FIELD_WEIGHTS = {
    "problem_category": 2.2,
    "title": 2.1,
    "content": 1.8,
    "tags": 1.5,
    "handling_result": 0.8,
    "reply_content": 0.8,
    "host_unit": 0.6,
    "company_name": 0.6,
    "location_point": 0.6,
    "extra_fields": 0.6,
}
FIELD_LABELS = {
    "problem_category": "问题分类",
    "title": "标题",
    "content": "主要内容",
    "tags": "标签",
    "handling_result": "办理结果",
    "reply_content": "回复内容",
    "host_unit": "主办单位",
    "company_name": "企业名称",
    "location_point": "小区点位",
    "extra_fields": "额外字段",
}
CORE_FIELDS = {"problem_category", "title", "content", "tags"}
MIN_CLASSIFICATION_SCORE = {
    MODULE_PUBLIC_INTEREST: 2.0,
    MODULE_VULNERABLE: 1.8,
    MODULE_ADMINISTRATIVE: 1.8,
}
CATEGORY_EXCLUDE_TERMS = {
    MODULE_PUBLIC_INTEREST: {
        "食品药品安全": ("食品经营许可证咨询", "食品许可证咨询", "咨询食品经营许可证", "办理食品证", "办理许可证", "许可证办理"),
        "未成年人保护": ("成年人", "成人"),
        "安全生产": ("安全咨询", "安全培训报名"),
    },
    MODULE_ADMINISTRATIVE: {
        "小过重罚": ("咨询罚款标准", "了解处罚标准"),
        "未按程序处罚": ("咨询办理程序",),
    },
}
CATEGORY_STRONG_TERMS = {
    MODULE_PUBLIC_INTEREST: {
        "食品药品安全": ("过期", "变质", "腹泻", "拉肚子", "三无", "假药", "食品安全", "餐饮卫生", "蟑螂"),
        "未成年人保护": ("未成年人", "未成年", "校园", "儿童", "学生", "孩子"),
        "安全生产": ("消防", "燃气", "坍塌", "安全隐患", "危化", "工地安全", "飞线充电"),
    },
    MODULE_VULNERABLE: {
        "农民工": ("农民工", "欠薪", "讨薪", "包工头", "工钱", "劳务费", "工地"),
    },
    MODULE_ADMINISTRATIVE: {
        "小过重罚": ("处罚过重", "罚款过重", "小过重罚", "过罚不当", "轻微违法"),
        "同案不同罚": ("同案不同罚", "处罚不一样", "标准不一", "执法不公"),
    },
}


def _text(order: WorkOrder) -> str:
    return " ".join(
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


def _extra_text(order: WorkOrder) -> str:
    raw = order.extra_fields or ""
    try:
        fields = json.loads(raw)
    except (TypeError, json.JSONDecodeError):
        return raw
    if not isinstance(fields, list):
        return raw
    chunks = []
    for item in fields:
        if isinstance(item, dict):
            chunks.append(f"{item.get('name', '')}{item.get('value', '')}")
    return " ".join(chunks)


def _field_texts(order: WorkOrder) -> dict[str, str]:
    return {
        "problem_category": order.problem_category or "",
        "title": order.title or "",
        "content": order.content or "",
        "tags": order.tags or "",
        "handling_result": order.handling_result or "",
        "reply_content": order.reply_content or "",
        "host_unit": order.host_unit or "",
        "company_name": order.company_name or "",
        "location_point": order.location_point or "",
        "extra_fields": _extra_text(order),
    }


def unknown_category(module: str) -> str:
    if module == MODULE_ADMINISTRATIVE:
        return ADMINISTRATIVE_UNKNOWN
    if module == MODULE_VULNERABLE:
        return VULNERABLE_UNKNOWN
    return PUBLIC_INTEREST_UNKNOWN


def _priority(score: float, order: WorkOrder, category: str, module: str) -> str:
    unresolved = order.is_resolved == "未解决"
    dissatisfied = order.satisfaction == "不满意"
    public_safety = any(word in (order.problem_category or "") for word in ["公共安全", "消防", "食品", "安全生产"])
    if score >= 6 or (unresolved and dissatisfied and public_safety) or "重大" in _text(order):
        return "高"
    if score >= 3 or unresolved or category != unknown_category(module):
        return "中"
    return "低"


def _rule_rows(rules: list[ScreeningRule] | None, module: str) -> list[tuple[str, str, list[str], float]]:
    if rules:
        return [
            (rule.name, rule.domain, [keyword.strip() for keyword in rule.keywords.split(",") if keyword.strip()], rule.weight)
            for rule in rules
            if rule.enabled and (rule.module or MODULE_PUBLIC_INTEREST) == module
        ]
    return [
        (rule.name, rule.domain, list(rule.keywords), rule.weight)
        for rule in DEFAULT_RULES
        if rule.module == module
    ]


def analyze_order(order: WorkOrder, rules: list[ScreeningRule] | None = None, module: str = MODULE_PUBLIC_INTEREST) -> dict:
    text = _text(order)
    field_texts = _field_texts(order)
    candidates: dict[str, dict] = defaultdict(lambda: {"score": 0.0, "keywords": set(), "fields": set(), "core_hits": 0, "rule_weight": 0.0})
    hit_names: list[str] = []
    evidence: list[str] = []

    for name, category, keywords, weight in _rule_rows(rules, module):
        rule_hits: dict[str, list[str]] = defaultdict(list)
        rule_score = 0.0
        core_hits = 0
        for keyword in keywords:
            if not keyword:
                continue
            for field, field_text in field_texts.items():
                if keyword in field_text:
                    rule_hits[keyword].append(FIELD_LABELS[field])
                    rule_score += weight * FIELD_WEIGHTS[field]
                    candidates[category]["fields"].add(field)
                    if field in CORE_FIELDS:
                        core_hits += 1
        if rule_hits:
            candidates[category]["score"] += rule_score
            candidates[category]["keywords"].update(rule_hits.keys())
            candidates[category]["core_hits"] += core_hits
            candidates[category]["rule_weight"] += weight
            compact_hits = list(rule_hits.keys())[:5]
            hit_names.append(f"{name}:{'、'.join(compact_hits)}")
            field_parts = [f"{keyword}（{'、'.join(labels[:3])}）" for keyword, labels in list(rule_hits.items())[:5]]
            evidence.append(f"命中{name}线索标注：{'；'.join(field_parts)}")

    if module == MODULE_PUBLIC_INTEREST and any(term in text for term in PUBLIC_INTEREST_TERMS):
        for category in list(candidates):
            if candidates[category]["fields"] & CORE_FIELDS:
                candidates[category]["score"] += 1.0
        if candidates:
            evidence.append("文本体现不特定多数人或公共利益影响")

    for category, meta in candidates.items():
        excludes = CATEGORY_EXCLUDE_TERMS.get(module, {}).get(category, ())
        strong_terms = CATEGORY_STRONG_TERMS.get(module, {}).get(category, ())
        if excludes and any(term in text for term in excludes) and not any(term in text for term in strong_terms):
            meta["score"] *= 0.2
            evidence.append(f"{category}命中内容主要为咨询/办理类表述，已降低自动分类强度")

    if not candidates:
        category = unknown_category(module)
        score = 0.5 if order.satisfaction == "不满意" else 0.1
    else:
        category, meta = max(
            candidates.items(),
            key=lambda item: (item[1]["score"], item[1]["core_hits"], len(item[1]["keywords"]), item[1]["rule_weight"]),
        )
        score = float(meta["score"])
        has_core_evidence = bool(meta["fields"] & CORE_FIELDS)
        if score < MIN_CLASSIFICATION_SCORE.get(module, 1.8) or not has_core_evidence:
            category = unknown_category(module)
            evidence.append("命中强度低于本地筛查阈值，归入其他/未知分类，待人工研判")

    if order.is_resolved == "未解决":
        score += 0.8
    if order.satisfaction == "不满意":
        score += 0.8
    if order.location_point:
        score += 0.4

    priority = _priority(score, order, category, module)
    fallback = "未命中本板块线索标注规则，归入其他/未知分类，待人工研判"
    return {
        "predicted_domain": category,
        "category": category,
        "risk_score": round(score, 2),
        "priority": priority,
        "rule_hits": "\n".join(hit_names),
        "evidence": "\n".join(dict.fromkeys(evidence)) or fallback,
    }


def _sync_public_interest_clue(db: Session, order: WorkOrder, result: dict) -> tuple[int, int]:
    existing = db.query(Clue).filter(Clue.work_order_id == order.id).first()
    if existing and existing.status == "已确认":
        existing.priority = result["priority"]
        existing.risk_score = result["risk_score"]
        existing.rule_hits = result["rule_hits"]
        existing.evidence = result["evidence"]
        existing.confidence = 0
        existing.updated_at = datetime.utcnow()
        order.case_domain = existing.predicted_domain
        return 0, 1
    if existing:
        existing.predicted_domain = result["category"]
        existing.priority = result["priority"]
        existing.risk_score = result["risk_score"]
        existing.confidence = 0
        existing.rule_hits = result["rule_hits"]
        existing.evidence = result["evidence"]
        existing.status = "待确认"
        existing.updated_at = datetime.utcnow()
        order.case_domain = result["category"]
        return 0, 1
    db.add(
        Clue(
            work_order_id=order.id,
            predicted_domain=result["category"],
            priority=result["priority"],
            risk_score=result["risk_score"],
            confidence=0,
            status="待确认",
            rule_hits=result["rule_hits"],
            evidence=result["evidence"],
        )
    )
    order.case_domain = result["category"]
    return 1, 0


def _upsert_classification(db: Session, order: WorkOrder, module: str, result: dict) -> tuple[int, int]:
    existing = (
        db.query(CaseClassification)
        .filter(CaseClassification.work_order_id == order.id, CaseClassification.module == module)
        .first()
    )
    if existing and existing.review_status == "已确认":
        existing.priority = result["priority"]
        existing.risk_score = result["risk_score"]
        existing.rule_hits = result["rule_hits"]
        existing.evidence = result["evidence"]
        existing.updated_at = datetime.utcnow()
        return 0, 1
    if existing:
        existing.category = result["category"]
        existing.priority = result["priority"]
        existing.risk_score = result["risk_score"]
        existing.rule_hits = result["rule_hits"]
        existing.evidence = result["evidence"]
        existing.review_status = "待确认"
        existing.updated_at = datetime.utcnow()
        return 0, 1
    db.add(
        CaseClassification(
            work_order_id=order.id,
            module=module,
            category=result["category"],
            priority=result["priority"],
            risk_score=result["risk_score"],
            rule_hits=result["rule_hits"],
            evidence=result["evidence"],
            review_status="待确认",
        )
    )
    return 1, 0


def run_screening(db: Session, batch_ids: list[int] | None = None, modules: list[str] | None = None) -> dict:
    selected_modules = [module for module in (modules or [MODULE_PUBLIC_INTEREST]) if module in SUPPORTED_MODULES]
    if not selected_modules:
        selected_modules = [MODULE_PUBLIC_INTEREST]

    query = db.query(WorkOrder)
    if batch_ids:
        query = query.filter(WorkOrder.batch_id.in_(batch_ids))
    work_orders = query.all()
    rules = db.query(ScreeningRule).all()

    classifications_created = 0
    classifications_updated = 0
    clues_created = 0
    clues_updated = 0
    for order in work_orders:
        for module in selected_modules:
            result = analyze_order(order, rules, module=module)
            created, updated = _upsert_classification(db, order, module, result)
            classifications_created += created
            classifications_updated += updated
            if module == MODULE_PUBLIC_INTEREST:
                c_created, c_updated = _sync_public_interest_clue(db, order, result)
                clues_created += c_created
                clues_updated += c_updated
    db.commit()
    clusters = rebuild_clusters(db)
    return {
        "processed": len(work_orders),
        "classified_work_orders": len(work_orders),
        "modules": selected_modules,
        "classifications_created": classifications_created,
        "classifications_updated": classifications_updated,
        "clues_created": clues_created,
        "clusters_created": clusters,
        "updated": classifications_updated + clues_updated,
    }


STOP_WORDS = {
    "投诉", "反映", "咨询", "问题", "情况", "要求", "希望", "处理", "解决", "相关", "部门", "工作人员",
    "居民", "群众", "小区", "社区", "街道", "房山", "北京市", "进行", "存在", "表示", "没有", "一直",
    "附近", "门口", "号楼", "楼栋", "单元", "底商", "该处", "现场", "位置", "地址",
}

GENERIC_OBJECT_VALUES = {
    "不详", "无", "未提供", "未知", "无具体地址", "同上", "本人", "群众", "居民", "市民",
    "小区", "社区", "街道", "村", "北京市", "房山区",
}

COMPANY_SUFFIX_RE = re.compile(r"(?:有限责任公司|股份有限公司|集团有限公司|有限公司|分公司|集团|公司)+$")
OBJECT_SUFFIXES = (
    "小区", "社区", "村", "号楼", "楼栋", "楼", "单元", "号院", "路", "街", "巷", "胡同",
    "工地", "项目", "工程", "市场", "商场", "超市", "学校", "幼儿园", "医院", "药店",
    "餐厅", "饭店", "门店", "店", "公司", "工厂", "厂", "园区", "停车场",
)
ISSUE_TERMS = {
    "供暖", "不热", "停水", "漏水", "噪声", "油烟", "食品", "药品", "过期", "腹泻",
    "停车", "占道", "垃圾", "污染", "排污", "异味", "消防", "燃气", "欠薪", "工资",
    "罚款", "处罚", "执法", "安全", "隐患", "电梯", "井盖", "塌陷", "诈骗",
}
CHINESE_DIGIT_MAP = str.maketrans({"零": "0", "一": "1", "二": "2", "两": "2", "三": "3", "四": "4", "五": "5", "六": "6", "七": "7", "八": "8", "九": "9"})


def _normalize_address_numbers(text: str) -> str:
    return re.sub(
        r"([零一二两三四五六七八九])(?=号楼|号院|单元|楼|层|号)",
        lambda match: match.group(1).translate(CHINESE_DIGIT_MAP),
        text,
    )


def _normalize(value: str | None) -> str:
    text = (value or "").strip()
    text = re.sub(r"\s+", "", text)
    text = re.sub(r"[，。,.;；:：、（）()【】\[\]<>《》\"'“”‘’]", "", text)
    return _normalize_address_numbers(text)


def _valid_object(value: str | None) -> str:
    normalized = _normalize(value)
    normalized = re.sub(r"^(?:群众|居民|市民|来电人|投诉人)?(?:多次|再次|反复)?(?:反映|投诉|举报|称|表示|咨询|位于|在)", "", normalized)
    if not normalized or normalized in GENERIC_OBJECT_VALUES or len(normalized) < 3:
        return ""
    return normalized[:60]


def _object_aliases(value: str | None) -> list[str]:
    normalized = _valid_object(value)
    if not normalized:
        return []
    aliases = [normalized]
    without_area = re.sub(r"^[\u4e00-\u9fa5]{2,12}(?:区|县|镇|乡|街道)", "", normalized)
    if len(without_area) >= 3 and without_area != normalized:
        aliases.append(without_area)
    address = re.search(r"([\u4e00-\u9fa5]{2,12}(?:路|街|巷|胡同)[0-9零一二两三四五六七八九十百千万-]{1,8}号)", normalized)
    if address:
        aliases.append(_valid_object(address.group(1)))
    return [alias for alias in dict.fromkeys(aliases) if alias]


def _company_aliases(value: str | None) -> list[str]:
    normalized = _valid_object(value)
    if not normalized:
        return []
    simplified = COMPANY_SUFFIX_RE.sub("", normalized)
    simplified = re.sub(r"^(?:北京市?|北京|房山区|良乡镇|长阳镇|城关街道)", "", simplified)
    aliases = [normalized]
    if len(simplified) >= 3 and simplified not in aliases:
        aliases.append(simplified)
    return aliases


def _text_object_candidates(text: str | None) -> list[str]:
    if not text:
        return []
    candidates: list[str] = []
    for fragment in re.split(r"[，。,.;；:：\n\r]", text):
        fragment = fragment.strip()
        if not fragment:
            continue
        for match in re.finditer(r"([\u4e00-\u9fa5]{2,12}(?:路|街|巷|胡同)[0-9零一二两三四五六七八九十百千万-]{1,8}号(?:院|楼|门店|底商)?)", fragment):
            candidate = _valid_object(match.group(1))
            if candidate:
                candidates.append(candidate)
        for match in re.finditer(r"([\u4e00-\u9fa5A-Za-z0-9]{2,20}(?:餐厅|饭店|药店|超市|市场|学校|医院|工地|项目|工程|公司|门店|店))(?:门口|内|外|附近|周边)?", fragment):
            candidate = _valid_object(match.group(1))
            if candidate:
                candidates.append(candidate)
        for match in re.finditer(r"([\u4e00-\u9fa5A-Za-z0-9]{2,28}(?:小区|社区|村|号楼|楼栋|单元|号院|路|街|巷|胡同|工地|项目|工程|市场|商场|超市|学校|幼儿园|医院|药店|餐厅|饭店|门店|店|公司|工厂|厂|园区|停车场))", fragment):
            candidate = _valid_object(match.group(1))
            if candidate:
                candidates.append(candidate)
                address = re.search(r"([\u4e00-\u9fa5]{2,12}(?:路|街|巷|胡同)[0-9零一二两三四五六七八九十百千万-]{1,8}号)", candidate)
                if address:
                    candidates.append(_valid_object(address.group(1)))
        for match in re.finditer(r"(?:位于|地址|地点|点位|发生在|在)([\u4e00-\u9fa5A-Za-z0-9]{2,28})", fragment):
            candidate = _valid_object(match.group(1))
            if candidate and any(suffix in candidate for suffix in OBJECT_SUFFIXES):
                candidates.append(candidate)
    return candidates


def _object_keys(order: WorkOrder) -> list[str]:
    keys: list[str] = []
    for alias in _company_aliases(order.company_name):
        keys.append(f"企业:{alias}")
    point = _valid_object(order.location_point)
    if point:
        for alias in _object_aliases(point):
            keys.append(f"点位:{alias}")
    text = "；".join([order.title or "", order.content or "", order.extra_fields or ""])
    for candidate in _text_object_candidates(text):
        for alias in _object_aliases(candidate):
            keys.append(f"对象:{alias}")
    return list(dict.fromkeys(keys))


def _tokenize(text: str) -> set[str]:
    compact = _normalize(text)
    chunks = re.findall(r"[\u4e00-\u9fa5A-Za-z0-9]{2,}", compact)
    tokens: set[str] = set()
    for chunk in chunks:
        if chunk not in STOP_WORDS and len(chunk) >= 2:
            tokens.add(chunk)
        for size in (2, 3, 4):
            for index in range(max(0, len(chunk) - size + 1)):
                token = chunk[index : index + size]
                if token not in STOP_WORDS:
                    tokens.add(token)
    return tokens


def _problem_text(order: WorkOrder) -> str:
    return " ".join([order.problem_category or "", order.tags or "", order.title or "", order.content or ""])


def _same_or_similar_problem(a: WorkOrder, b: WorkOrder) -> bool:
    a_category = _normalize(a.problem_category)
    b_category = _normalize(b.problem_category)
    if a_category and b_category and (a_category == b_category or a_category in b_category or b_category in a_category):
        return True
    return difflib.SequenceMatcher(None, a_category, b_category).ratio() >= 0.78 if a_category and b_category else True


def _same_complainant(a: WorkOrder, b: WorkOrder) -> bool:
    a_phone = _normalize(a.caller_phone)
    b_phone = _normalize(b.caller_phone)
    if a_phone and b_phone and a_phone == b_phone:
        return True
    a_name = _normalize(a.caller_name)
    b_name = _normalize(b.caller_name)
    return bool(a_name and b_name and a_name == b_name)


def _issue_similarity(a: WorkOrder, b: WorkOrder) -> tuple[bool, str]:
    a_text = _problem_text(a)
    b_text = _problem_text(b)
    title_ratio = difflib.SequenceMatcher(None, _normalize(a.title)[:160], _normalize(b.title)[:160]).ratio()
    body_ratio = difflib.SequenceMatcher(None, _normalize(a_text)[:420], _normalize(b_text)[:420]).ratio()
    shared = sorted((_tokenize(a_text) & _tokenize(b_text)) - STOP_WORDS, key=len, reverse=True)
    significant_shared = [token for token in shared if len(token) >= 3 or token in ISSUE_TERMS]
    issue_shared = [token for token in shared if token in ISSUE_TERMS]
    similar = _same_or_similar_problem(a, b) and len(significant_shared) >= 1 and (
        title_ratio >= 0.56
        or body_ratio >= 0.50
        or (len(issue_shared) >= 2 and (title_ratio >= 0.35 or body_ratio >= 0.38))
    )
    complainant_text = "，投诉人信息一致" if _same_complainant(a, b) else ""
    reason = f"同一具体对象，问题分类相近{complainant_text}，共享关键词：{'、'.join(significant_shared[:6])}，标题相似度 {title_ratio:.2f}，内容相似度 {body_ratio:.2f}"
    return similar, reason


def _choose_representative(members: list[WorkOrder]) -> WorkOrder:
    return sorted(
        members,
        key=lambda item: (
            -(len(item.title or "") + len(item.content or "") + len(item.handling_result or "") + len(item.reply_content or "")),
            item.closed_at or item.created_at,
            item.id,
        ),
    )[0]


def _event_time(order: WorkOrder) -> datetime:
    return order.received_at or order.closed_at or order.created_at or datetime.utcnow()


def rebuild_clusters(db: Session) -> int:
    db.query(ClusterMember).delete()
    db.query(EventCluster).delete()
    db.commit()

    orders = db.query(WorkOrder).all()
    parent = {order.id: order.id for order in orders}
    buckets: dict[str, list[WorkOrder]] = defaultdict(list)
    for order in orders:
        for key in _object_keys(order):
            buckets[key].append(order)

    def find(order_id: int) -> int:
        while parent[order_id] != order_id:
            parent[order_id] = parent[parent[order_id]]
            order_id = parent[order_id]
        return order_id

    reasons: dict[tuple[int, int], str] = {}

    def union(a_id: int, b_id: int, reason: str) -> None:
        a_root = find(a_id)
        b_root = find(b_id)
        if a_root != b_root:
            parent[b_root] = a_root
        reasons[tuple(sorted((a_id, b_id)))] = reason

    for key, bucket in buckets.items():
        if len(bucket) < 2:
            continue
        for index, current in enumerate(bucket):
            for other in bucket[index + 1 :]:
                similar, reason = _issue_similarity(current, other)
                if similar:
                    union(current.id, other.id, f"{key}；{reason}")

    components: dict[int, list[WorkOrder]] = defaultdict(list)
    for order in orders:
        components[find(order.id)].append(order)

    created = 0
    cluster_index = 1
    for members in components.values():
        if len(members) < 2:
            continue
        representative = _choose_representative(members)
        member_ids = {item.id for item in members}
        reason_text = next(
            (reason for pair, reason in reasons.items() if pair[0] in member_ids and pair[1] in member_ids),
            "同一具体对象，问题分类和标题/内容高度相近",
        )
        cluster_key = f"event-{cluster_index}"
        cluster_index += 1
        members_sorted = sorted(members, key=_event_time)
        unresolved = sum(1 for item in members if item.is_resolved == "未解决")
        dissatisfied = sum(1 for item in members if item.satisfaction == "不满意")
        if len(members) >= 8 or unresolved >= 5 or dissatisfied >= 5:
            risk = "高"
        elif len(members) >= 3 or unresolved >= 2 or dissatisfied >= 2:
            risk = "中"
        else:
            risk = "低"
        cluster = EventCluster(
            cluster_key=cluster_key,
            title=representative.title or representative.problem_category or "屡诉未决事件",
            domain="",
            representative_order_id=representative.id,
            match_reason=reason_text,
            location_point=representative.location_point,
            town=representative.town,
            complaint_count=len(members),
            unresolved_count=unresolved,
            dissatisfied_count=dissatisfied,
            risk_level=risk,
            first_seen_at=_event_time(members_sorted[0]),
            last_seen_at=_event_time(members_sorted[-1]),
        )
        db.add(cluster)
        db.flush()
        for member in sorted(members, key=lambda item: (find(item.id), _event_time(item), item.id)):
            db.add(ClusterMember(cluster_id=cluster.id, work_order_id=member.id))
        created += 1
    db.commit()
    return created
