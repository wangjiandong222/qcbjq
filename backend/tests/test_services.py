from types import SimpleNamespace
from datetime import datetime, timedelta

from openpyxl import Workbook
from openpyxl.utils.datetime import to_excel
from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker

from app.core.database import Base
from app.core.security import hash_password, verify_password
from app.api.routes import batch_review_classifications, classifications, create_rule, dashboard, work_orders
from app.init_db import seed_roles_users
from app.schemas.dto import ClassificationBatchReviewRequest, RuleCreateRequest
from app.models.entities import CaseClassification, Clue, ClusterMember, EventCluster, Role, ScreeningRule, User, WorkOrder
from app.services.analysis import cluster_intervention_assessment, performance_anomalies, trend_analysis
from app.services.importer import import_workbook
from app.services.exports import EXPORT_DIR, create_export, create_selected_export, extract_wage_fields, format_wage_core
from app.services.rules import seed_rule_rows
from app.services.screening import UNKNOWN_DOMAIN, analyze_order, rebuild_clusters, run_screening


def make_order(**overrides):
    data = {
        "problem_category": "",
        "tags": "",
        "title": "",
        "content": "",
        "handling_result": "",
        "reply_content": "",
        "company_name": "",
        "host_unit": "",
        "location_point": "",
        "extra_fields": "",
        "case_domain": "",
        "is_resolved": "未解决",
        "satisfaction": "不满意",
    }
    data.update(overrides)
    return SimpleNamespace(**data)


def test_order_raw_identity_can_be_preserved():
    order = WorkOrder(order_no="热线-raw", caller_name="张三", caller_phone="13812345678", content="电话13812345678")
    assert order.caller_name == "张三"
    assert order.caller_phone == "13812345678"
    assert "13812345678" in order.content


def test_screening_no_longer_uses_wage_as_labeling_module():
    db = make_db()
    db.add(WorkOrder(order_no="W0", title="某工地拖欠工资", content="包工头拖欠农民工工资，大家都在讨薪。"))
    db.commit()

    result = run_screening(db, modules=["wage"])

    assert "wage" not in result["modules"]
    assert db.query(CaseClassification).filter(CaseClassification.module == "wage").count() == 0
    db.close()


def test_screening_detects_public_interest_food_safety():
    order = make_order(title="小吃店多人腹泻", content="好多孩子在这家店吃完拉肚子，附近居民都受影响。")
    result = analyze_order(order)
    assert result["predicted_domain"] == "食品药品安全"
    assert "confidence" not in result


def test_screening_uses_core_field_weight_over_auxiliary_text():
    order = make_order(
        title="小吃店多人腹泻",
        content="多名孩子在店内就餐后腹泻，附近居民担心食品安全。",
        reply_content="另有群众提到工资咨询，已告知反映渠道。",
    )
    result = analyze_order(order)
    assert result["predicted_domain"] == "食品药品安全"


def test_screening_excludes_food_license_consulting_from_food_safety():
    order = make_order(title="咨询食品经营许可证办理", content="想了解食品经营许可证办理材料和流程。")

    result = analyze_order(order)

    assert result["predicted_domain"] == UNKNOWN_DOMAIN
    assert "咨询/办理类表述" in result["evidence"]


def test_screening_conflict_prefers_stronger_core_food_evidence():
    order = make_order(title="小吃店过期食品导致腹泻", content="多名孩子吃坏肚子，居民担心食品安全。")

    result = analyze_order(order)

    assert result["predicted_domain"] == "食品药品安全"


def test_screening_keeps_weak_auxiliary_hit_unknown():
    order = make_order(title="普通咨询", content="咨询一般事项", reply_content="已告知工资问题可咨询人社部门。")
    result = analyze_order(order)
    assert result["predicted_domain"] == UNKNOWN_DOMAIN


def test_screening_ignores_imported_case_domain_gold_label():
    order = make_order(
        title="某工地拖欠工资",
        content="包工头拖欠农民工工资，工人正在讨薪。",
        case_domain="公益诉讼（食品药品安全）",
    )
    result = analyze_order(order, module="vulnerable")
    assert result["predicted_domain"] == "农民工"
    assert "样例数据含金标准" not in result["evidence"]


def make_db():
    engine = create_engine("sqlite:///:memory:", connect_args={"check_same_thread": False})
    Base.metadata.create_all(engine)
    return sessionmaker(bind=engine)()


def test_seed_roles_users_repairs_demo_accounts():
    db = make_db()
    old_role = Role(name="old", display_name="旧角色", permissions="read")
    db.add(old_role)
    db.flush()
    db.add(
        User(
            username="admin",
            display_name="旧管理员",
            password_hash=hash_password("wrong-password"),
            role_id=old_role.id,
            is_active=False,
        )
    )
    db.commit()

    seed_roles_users(db)

    admin = db.query(User).filter(User.username == "admin").first()
    assert admin is not None
    assert admin.display_name == "系统管理员"
    assert admin.is_active is True
    assert admin.role.name == "admin"
    assert verify_password("admin123", admin.password_hash)
    assert db.query(User).filter(User.username == "prosecutor").first() is not None
    db.close()


def write_workbook(path, rows):
    wb = Workbook()
    ws = wb.active
    for row in rows:
        ws.append(row)
    wb.save(path)


def test_import_workbook_reads_sample_shape_and_updates_duplicates(tmp_path):
    db = make_db()
    path = tmp_path / "orders.xlsx"
    write_workbook(
        path,
        [
            ["说明行", "", ""],
            ["工单编号", "标题", "主要内容", "工单状态", "被反映街乡镇"],
            ["热线-001", "井盖破损", "小区门口井盖破损", "已办结", "长阳镇"],
        ],
    )

    first = import_workbook(db, path, "admin")
    assert first.status == "success"
    second = import_workbook(db, path, "admin")

    assert second.status == "success"
    assert second.success_rows == 1
    assert db.query(WorkOrder).count() == 2
    assert db.query(WorkOrder).first().town == "长阳镇"
    db.close()


def test_import_workbook_keeps_previous_batches_and_ignores_case_domain(tmp_path):
    db = make_db()
    first_path = tmp_path / "first.xlsx"
    second_path = tmp_path / "second.xlsx"
    write_workbook(
        first_path,
        [
            ["工单编号", "标题", "主要内容"],
            ["热线-001", "旧数据", "旧内容"],
        ],
    )
    write_workbook(
        second_path,
        [
            ["工单编号", "标题", "主要内容", "成案领域"],
            ["热线-002", "新数据", "新内容", "不应导入的领域"],
        ],
    )

    import_workbook(db, first_path, "admin")
    batch = import_workbook(db, second_path, "admin")

    assert batch.status == "success"
    assert db.query(WorkOrder).count() == 2
    order = db.query(WorkOrder).filter(WorkOrder.order_no == "热线-002").first()
    assert order.order_no == "热线-002"
    assert order.case_domain == ""
    db.close()


def test_import_workbook_accepts_unknown_headers_as_extra_fields(tmp_path):
    db = make_db()
    path = tmp_path / "extra.xlsx"
    write_workbook(path, [["序号", "备注"], ["1", "缺少标准字段"]])

    batch = import_workbook(db, path, "admin")

    assert batch.status == "success"
    order = db.query(WorkOrder).first()
    assert order.order_no == ""
    assert '"序号"' in order.extra_fields
    assert '"备注"' in order.extra_fields
    db.close()


def test_import_workbook_accepts_header_aliases(tmp_path):
    db = make_db()
    path = tmp_path / "aliases.xlsx"
    write_workbook(
        path,
        [
            ["编号", "诉求内容", "乡镇街道", "详细地址"],
            ["热线-003", "小区门口餐饮油烟扰民，居民多次投诉。", "城关街道", "某小区底商"],
        ],
    )

    batch = import_workbook(db, path, "admin")

    assert batch.status == "success"
    order = db.query(WorkOrder).first()
    assert order.order_no == "热线-003"
    assert order.title.startswith("小区门口餐饮")
    assert order.content == "小区门口餐饮油烟扰民，居民多次投诉。"
    assert order.town == "城关街道"
    assert order.location_point == "某小区底商"
    db.close()


def test_import_workbook_parses_common_government_dates(tmp_path):
    db = make_db()
    path = tmp_path / "dates.xlsx"
    write_workbook(
        path,
        [
            ["工单编号", "标题", "来电时间", "办结时间"],
            ["D1", "中文日期", "2024年1月2日", "2024年1月3日 9时30分"],
            ["D2", "点分隔", "2024.01.04", "2024/1/5 9:30"],
            ["D3", "紧凑日期", "20240106",  to_excel(datetime(2024, 1, 7, 10, 15))],
            ["D4", "下午日期", "2024年1月8日下午3时", "2024/1/8 上午12:05"],
        ],
    )

    batch = import_workbook(db, path, "admin")

    assert batch.status == "success"
    rows = {item.order_no: item for item in db.query(WorkOrder).all()}
    assert rows["D1"].received_at == datetime(2024, 1, 2)
    assert rows["D1"].closed_at == datetime(2024, 1, 3, 9, 30)
    assert rows["D2"].received_at == datetime(2024, 1, 4)
    assert rows["D2"].closed_at == datetime(2024, 1, 5, 9, 30)
    assert rows["D3"].received_at == datetime(2024, 1, 6)
    assert rows["D3"].closed_at == datetime(2024, 1, 7, 10, 15)
    assert rows["D4"].received_at == datetime(2024, 1, 8, 15, 0)
    assert rows["D4"].closed_at == datetime(2024, 1, 8, 0, 5)
    db.close()


def test_import_workbook_leaves_invalid_dates_empty(tmp_path):
    db = make_db()
    path = tmp_path / "bad-date.xlsx"
    write_workbook(path, [["工单编号", "标题", "来电时间"], ["D4", "无效日期", "不是日期"]])

    batch = import_workbook(db, path, "admin")

    assert batch.status == "success"
    assert db.query(WorkOrder).first().received_at is None
    db.close()


def test_import_workbook_preserves_host_unit_and_extra_columns(tmp_path):
    db = make_db()
    path = tmp_path / "host-extra.xlsx"
    write_workbook(
        path,
        [
            ["工单编号", "标题", "主办单位", "自定义列"],
            ["热线-004", "测试标题", "房山区某单位", "额外内容"],
        ],
    )

    batch = import_workbook(db, path, "admin")

    assert batch.status == "success"
    order = db.query(WorkOrder).first()
    assert order.host_unit == "房山区某单位"
    assert '"自定义列"' in order.extra_fields
    assert '"额外内容"' in order.extra_fields
    db.close()


def test_run_screening_creates_unknown_domain_for_every_order():
    db = make_db()
    db.add(WorkOrder(order_no="热线-005", title="普通咨询", content="咨询一般事项"))
    db.commit()

    result = run_screening(db)

    assert result["processed"] == 1
    clue = db.query(Clue).first()
    assert clue.predicted_domain == UNKNOWN_DOMAIN
    assert clue.status == "待确认"
    classification = db.query(CaseClassification).first()
    assert classification.category == UNKNOWN_DOMAIN
    assert classification.review_status == "待确认"
    db.close()


def test_run_screening_preserves_confirmed_domain():
    db = make_db()
    order = WorkOrder(order_no="热线-006", title="普通咨询", content="咨询一般事项")
    db.add(order)
    db.flush()
    db.add(Clue(work_order_id=order.id, predicted_domain="人工领域", status="已确认", priority="中", risk_score=1))
    db.add(ScreeningRule(name="普通规则", domain="规则领域", keywords="普通", weight=1, enabled=True))
    db.commit()

    run_screening(db)

    clue = db.query(Clue).first()
    assert clue.predicted_domain == "人工领域"
    assert clue.status == "已确认"
    assert db.query(WorkOrder).first().case_domain == "人工领域"
    db.close()


def test_run_screening_can_create_vulnerable_and_administrative_classifications():
    db = make_db()
    db.add(WorkOrder(order_no="热线-008", title="老人被罚款", content="老人反映轻微违法被处罚过重，要求处理。"))
    db.commit()

    result = run_screening(db, modules=["vulnerable", "administrative"])

    assert result["processed"] == 1
    rows = db.query(CaseClassification).all()
    assert {row.module for row in rows} == {"vulnerable", "administrative"}
    assert any(row.category == "老人" for row in rows)
    assert any(row.category == "小过重罚" for row in rows)
    db.close()


def test_dashboard_counts_high_risk_and_pending_reviews_by_distinct_work_order():
    db = make_db()
    first = WorkOrder(order_no="D1", title="同一工单多板块高风险")
    second = WorkOrder(order_no="D2", title="另一高风险工单")
    db.add_all([first, second])
    db.flush()
    db.add(CaseClassification(work_order_id=first.id, module="public_interest", category="安全生产", priority="高", review_status="待确认"))
    db.add(CaseClassification(work_order_id=first.id, module="administrative", category="未按程序处罚", priority="高", review_status="待确认"))
    db.add(CaseClassification(work_order_id=second.id, module="vulnerable", category="老人", priority="高", review_status="待确认"))
    db.commit()

    summary = dashboard(db=db, user=SimpleNamespace())

    assert summary.work_orders == 2
    assert summary.high_risk == 2
    assert summary.pending_reviews == 2
    db.close()


def test_classifications_can_dedupe_high_risk_work_orders_with_public_interest_first():
    db = make_db()
    first = WorkOrder(order_no="A1", title="同一工单多板块高风险")
    second = WorkOrder(order_no="A2", title="另一高风险工单")
    db.add_all([first, second])
    db.flush()
    db.add(CaseClassification(work_order_id=first.id, module="administrative", category="选择性执法", priority="高", risk_score=9))
    db.add(CaseClassification(work_order_id=first.id, module="public_interest", category="安全生产", priority="高", risk_score=5))
    db.add(CaseClassification(work_order_id=second.id, module="vulnerable", category="老人", priority="高", risk_score=6))
    db.commit()

    page = classifications(page=1, page_size=10, module="", priority="高", dedupe_work_orders=True, db=db, user=SimpleNamespace())

    assert page.total == 2
    assert [item["work_order_id"] for item in page.items].count(first.id) == 1
    first_row = next(item for item in page.items if item["work_order_id"] == first.id)
    assert first_row["module"] == "public_interest"
    db.close()


def test_export_confirmed_domains_includes_extra_fields(tmp_path):
    db = make_db()
    order = WorkOrder(
        order_no="热线-007",
        title="确认导出",
        content="完整内容",
        host_unit="主办单位A",
        extra_fields='[{"name":"自定义列","value":"自定义值"}]',
    )
    db.add(order)
    db.flush()
    db.add(
        Clue(
            work_order_id=order.id,
            predicted_domain="人工确认领域",
            status="已确认",
            priority="中",
            risk_score=2.5,
            reviewer="admin",
            review_note="确认无误",
        )
    )
    db.commit()

    task = create_export(db, "confirmed_domains", "admin")

    from openpyxl import load_workbook

    wb = load_workbook(task.file_path)
    ws = wb.active
    headers = [cell.value for cell in ws[1]]
    values = [cell.value for cell in ws[2]]
    row = dict(zip(headers, values))
    assert "置信度" not in headers
    assert row["主办单位"] == "主办单位A"
    assert row["人工确认成案领域"] == "人工确认领域"
    assert row["自定义列"] == "自定义值"
    from pathlib import Path
    Path(task.file_path).unlink(missing_ok=True)
    db.close()


def test_wage_export_puts_core_extraction_in_second_column(tmp_path):
    db = make_db()
    order = WorkOrder(
        order_no="热线-009",
        title="长阳回迁房二期项目拖欠工资",
        content="十名工人在长阳回迁房二期项目施工，施工地点为长阳镇稻田路8号，开工时间2024年3月，被包工头王某拖欠工资20万元，没有劳动合同。",
        location_point="长阳镇稻田路8号",
    )
    db.add(order)
    db.commit()

    task = create_selected_export(db, "wage", "admin", [order.id])

    from openpyxl import load_workbook
    wb = load_workbook(task.file_path)
    ws = wb.active
    headers = [cell.value for cell in ws[1]]
    row = [cell.value for cell in ws[2]]
    assert headers[0] == "工单编号"
    assert headers[1] == "核心内容提炼"
    assert "工程项目名称：长阳回迁房二期项目" in row[1]
    assert "工程地点：长阳镇稻田路8号" in row[1]
    assert "开工时间：2024年3月" in row[1]
    assert "工人人数：十名工人" in row[1]
    assert "欠薪主体：王某" in row[1]
    assert "欠薪数额：20万元" in row[1]
    assert "是否签订劳动合同：否" in row[1]
    assert "\n工程地点" in row[1]
    assert ws["B2"].alignment.wrap_text is True
    assert db.get(WorkOrder, order.id).exported_at is not None
    from pathlib import Path
    Path(task.file_path).unlink(missing_ok=True)
    db.close()


def test_wage_extractor_returns_empty_for_uncertain_project_and_unrelated_amount():
    order = WorkOrder(
        order_no="热线-010",
        title="某项目拖欠工资",
        content="群众反映被罚款200元，同时咨询工资问题；未明确项目名称、欠薪金额和合同情况。",
    )

    fields = extract_wage_fields(order)

    assert fields["工程项目名称"] == "无"
    assert fields["欠薪数额"] == "无"
    assert fields["是否签订劳动合同"] == "无"
    formatted = format_wage_core(fields)
    assert formatted.splitlines()[0] == "工程项目名称：无"


def test_wage_extractor_detects_positive_contract_only_when_explicit():
    order = WorkOrder(
        order_no="热线-011",
        title="拖欠工资",
        content="工程名称为青龙湖道路改造工程，工人与施工单位签订了劳动合同，工资被拖欠3万元。",
    )

    fields = extract_wage_fields(order)

    assert fields["工程项目名称"] == "青龙湖道路改造工程"
    assert fields["欠薪数额"] == "3万元"
    assert fields["是否签订劳动合同"] == "是"


def test_wage_extractor_handles_project_location_range_amount_and_worker_group():
    order = WorkOrder(
        order_no="热线-012",
        title="农民工讨薪",
        content="我们是在良乡镇一个叫翠堤春晓住宅项目干活，做水电安装，包工头刘某从去年11月开始就发了点生活费，工资一直没结清。我们一个班组十几个人，总共欠薪十五六万，没签合同。",
    )

    fields = extract_wage_fields(order)

    assert fields["工程项目名称"] == "翠堤春晓住宅项目"
    assert fields["工程地点"] == "良乡镇"
    assert fields["开工时间"] == "去年11月"
    assert fields["工人人数"] == "十几个人"
    assert fields["欠薪主体"] == "刘某"
    assert fields["欠薪数额"] == "十五六万"
    assert fields["是否签订劳动合同"] == "否"


def test_rebuild_clusters_requires_same_specific_issue_not_same_location_only():
    db = make_db()
    db.add_all(
        [
            WorkOrder(order_no="A1", location_point="阳光小区", problem_category="物业管理", title="阳光小区电梯反复停运", content="阳光小区1号楼电梯停运多日，老人上下楼困难。"),
            WorkOrder(order_no="A2", location_point="阳光小区", problem_category="物业管理", title="阳光小区电梯又停运", content="阳光小区1号楼电梯再次停运，希望尽快维修。"),
            WorkOrder(order_no="B1", location_point="阳光小区", problem_category="环境卫生", title="阳光小区垃圾桶异味", content="阳光小区南门垃圾桶异味严重，要求清理。"),
        ]
    )
    db.commit()

    created = rebuild_clusters(db)

    assert created == 1
    cluster = db.query(EventCluster).first()
    assert cluster.complaint_count == 2
    assert cluster.representative_order_id is not None
    assert "共享关键词" in cluster.match_reason
    db.close()


def test_work_orders_identify_duplicates_collapses_to_representative():
    db = make_db()
    first = WorkOrder(order_no="E1", title="A事件第一次投诉", problem_category="供暖", location_point="同一小区2号楼", closed_at=datetime(2025, 1, 1))
    representative = WorkOrder(order_no="E2", title="A事件代表投诉", problem_category="供暖", location_point="同一小区2号楼", closed_at=datetime(2025, 1, 2))
    single = WorkOrder(order_no="S1", title="普通单次投诉", problem_category="环境", location_point="另一点位", closed_at=datetime(2025, 1, 3))
    db.add_all([first, representative, single])
    db.flush()
    cluster = EventCluster(
        cluster_key="cluster-a",
        title="A事件代表投诉",
        domain="供暖",
        representative_order_id=representative.id,
        complaint_count=2,
        location_point="同一小区2号楼",
        match_reason="同一具体事项",
    )
    db.add(cluster)
    db.flush()
    db.add_all([ClusterMember(cluster_id=cluster.id, work_order_id=first.id), ClusterMember(cluster_id=cluster.id, work_order_id=representative.id)])
    db.commit()

    page = work_orders(page=1, page_size=20, identify_duplicates=True, db=db, user=SimpleNamespace())

    assert page.total == 2
    duplicate_rows = [item for item in page.items if item["is_duplicate_representative"]]
    assert len(duplicate_rows) == 1
    assert duplicate_rows[0]["id"] == representative.id
    assert duplicate_rows[0]["cluster_id"] == cluster.id
    assert duplicate_rows[0]["cluster_member_count"] == 2
    assert {item["order_no"] for item in page.items} == {"E2", "S1"}

    filtered = work_orders(page=1, page_size=20, q="第一次", search_mode="keyword", identify_duplicates=True, db=db, user=SimpleNamespace())
    assert filtered.total == 1
    assert filtered.items[0]["order_no"] == "E2"
    assert filtered.items[0]["is_duplicate_representative"] is True
    db.close()


def test_work_order_semantic_search_expands_real_world_wage_terms():
    db = make_db()
    db.add_all(
        [
            WorkOrder(order_no="QX1", title="项目劳务纠纷", content="农民工反映包工头长期欠薪，工钱一直未结清。"),
            WorkOrder(order_no="QT1", title="停车问题", content="反映小区停车收费争议。"),
        ]
    )
    db.commit()

    page = work_orders(page=1, page_size=20, q="拖欠工资", search_field="all", search_mode="semantic", db=db, user=SimpleNamespace())

    assert page.total == 1
    assert page.items[0]["order_no"] == "QX1"
    db.close()


def test_work_order_keyword_search_expands_wage_terms_and_ranks_core_fields():
    db = make_db()
    db.add_all(
        [
            WorkOrder(order_no="K1", title="停车问题", content="办理结果中提到可咨询工资问题。"),
            WorkOrder(order_no="K2", title="农民工欠薪求助", content="包工头拖欠工钱，班组一直未结清。"),
            WorkOrder(order_no="K3", title="普通咨询", content="咨询小区物业事项。"),
        ]
    )
    db.commit()

    page = work_orders(page=1, page_size=20, q="拖欠工资", search_field="all", search_mode="keyword", db=db, user=SimpleNamespace())

    assert page.total == 2
    assert page.items[0]["order_no"] == "K2"
    assert {item["order_no"] for item in page.items} == {"K1", "K2"}
    db.close()


def test_work_order_all_field_search_does_not_drop_non_fts_field_matches():
    db = make_db()
    db.add_all(
        [
            WorkOrder(order_no="FTS1", title="拖欠工资事项", content="标题命中。"),
            WorkOrder(order_no="AUX1", title="普通咨询", handling_result="办理结果中提到拖欠工资。"),
        ]
    )
    db.commit()
    db.execute(
        text(
            """
            CREATE VIRTUAL TABLE work_order_fts USING fts5(
                order_no, title, content, problem_category, tags,
                company_name, location_point, extra_fields, tokenize='trigram'
            )
            """
        )
    )
    db.execute(
        text(
            """
            INSERT INTO work_order_fts(
                rowid, order_no, title, content, problem_category, tags,
                company_name, location_point, extra_fields
            )
            SELECT
                id, COALESCE(order_no, ''), COALESCE(title, ''), COALESCE(content, ''),
                COALESCE(problem_category, ''), COALESCE(tags, ''), COALESCE(company_name, ''),
                COALESCE(location_point, ''), COALESCE(extra_fields, '')
            FROM work_orders
            """
        )
    )
    db.commit()

    page = work_orders(page=1, page_size=20, q="拖欠工资", search_field="all", search_mode="keyword", db=db, user=SimpleNamespace())

    assert page.total == 2
    assert {item["order_no"] for item in page.items} == {"FTS1", "AUX1"}
    db.close()


def test_work_order_keyword_search_covers_phone_and_extra_fields():
    db = make_db()
    db.add(
        WorkOrder(
            order_no="EX1",
            title="额外字段检索",
            caller_phone="13800001111",
            extra_fields='[{"name":"派单编号","value":"PD-2026-001"}]',
        )
    )
    db.commit()

    phone_page = work_orders(page=1, page_size=20, q="13800001111", search_field="caller_phone", search_mode="keyword", db=db, user=SimpleNamespace())
    extra_page = work_orders(page=1, page_size=20, q="PD-2026-001", search_field="extra_fields", search_mode="keyword", db=db, user=SimpleNamespace())

    assert phone_page.total == 1
    assert extra_page.total == 1
    assert phone_page.items[0]["order_no"] == "EX1"
    assert extra_page.items[0]["order_no"] == "EX1"
    db.close()


def test_classifications_identify_duplicates_collapses_to_representative_context():
    db = make_db()
    first = WorkOrder(order_no="F1", title="未知领域第一次", problem_category="综合")
    representative = WorkOrder(order_no="F2", title="未知领域代表", problem_category="综合")
    single = WorkOrder(order_no="F3", title="未知领域单条", problem_category="综合")
    db.add_all([first, representative, single])
    db.flush()
    cluster = EventCluster(cluster_key="cluster-f", title="未知领域代表", domain=UNKNOWN_DOMAIN, representative_order_id=representative.id, complaint_count=2, match_reason="同一事项")
    db.add(cluster)
    db.flush()
    db.add_all([ClusterMember(cluster_id=cluster.id, work_order_id=first.id), ClusterMember(cluster_id=cluster.id, work_order_id=representative.id)])
    db.add_all(
        [
            CaseClassification(work_order_id=first.id, module="public_interest", category=UNKNOWN_DOMAIN, priority="中", risk_score=5),
            CaseClassification(work_order_id=representative.id, module="public_interest", category=UNKNOWN_DOMAIN, priority="中", risk_score=4),
            CaseClassification(work_order_id=single.id, module="public_interest", category=UNKNOWN_DOMAIN, priority="低", risk_score=1),
        ]
    )
    db.commit()

    page = classifications(page=1, page_size=20, module="public_interest", category=UNKNOWN_DOMAIN, identify_duplicates=True, db=db, user=SimpleNamespace())

    assert page.total == 2
    duplicate_row = next(item for item in page.items if item["is_duplicate_representative"])
    assert duplicate_row["work_order_id"] == representative.id
    assert duplicate_row["cluster_id"] == cluster.id
    assert duplicate_row["duplicate_event"]["complaint_count"] == 2
    assert {item["order_no"] for item in page.items} == {"F2", "F3"}
    db.close()


def test_alert_center_identify_duplicates_dedupes_and_collapses_to_representative():
    db = make_db()
    first = WorkOrder(order_no="AR1", title="高风险重复成员", problem_category="食品安全")
    representative = WorkOrder(order_no="AR2", title="高风险重复代表", problem_category="食品安全")
    single = WorkOrder(order_no="AR3", title="高风险单条", problem_category="安全生产")
    db.add_all([first, representative, single])
    db.flush()
    cluster = EventCluster(cluster_key="cluster-alert", title="高风险重复代表", domain="食品药品安全", representative_order_id=representative.id, complaint_count=2)
    db.add(cluster)
    db.flush()
    db.add_all([ClusterMember(cluster_id=cluster.id, work_order_id=first.id), ClusterMember(cluster_id=cluster.id, work_order_id=representative.id)])
    db.add_all(
        [
            CaseClassification(work_order_id=first.id, module="administrative", category="其他", priority="高", risk_score=9),
            CaseClassification(work_order_id=first.id, module="public_interest", category="食品药品安全", priority="高", risk_score=7),
            CaseClassification(work_order_id=representative.id, module="public_interest", category="食品药品安全", priority="高", risk_score=5),
            CaseClassification(work_order_id=single.id, module="public_interest", category="安全生产", priority="高", risk_score=8),
        ]
    )
    db.commit()

    page = classifications(page=1, page_size=20, module="", priority="高", identify_duplicates=True, dedupe_work_orders=True, db=db, user=SimpleNamespace())

    assert page.total == 2
    duplicate_row = next(item for item in page.items if item["is_duplicate_representative"])
    assert duplicate_row["work_order_id"] == representative.id
    assert duplicate_row["cluster_id"] == cluster.id
    assert {item["order_no"] for item in page.items} == {"AR2", "AR3"}
    assert [item for item in page.items if item["work_order_id"] == first.id] == []
    db.close()


def test_duplicate_representative_export_can_include_all_cluster_members(tmp_path):
    db = make_db()
    first = WorkOrder(order_no="X1", title="重复事件成员1")
    representative = WorkOrder(order_no="X2", title="重复事件代表")
    single = WorkOrder(order_no="X3", title="普通工单")
    db.add_all([first, representative, single])
    db.flush()
    cluster = EventCluster(cluster_key="cluster-x", title="重复事件代表", domain="综合", representative_order_id=representative.id, complaint_count=2)
    db.add(cluster)
    db.flush()
    db.add_all([ClusterMember(cluster_id=cluster.id, work_order_id=first.id), ClusterMember(cluster_id=cluster.id, work_order_id=representative.id)])
    db.commit()

    task = create_selected_export(
        db,
        "work_orders",
        "admin",
        work_order_ids=[single.id],
        cluster_ids=[cluster.id],
        representative_work_order_ids=[representative.id],
        duplicate_export_scope="all_members",
    )

    from openpyxl import load_workbook

    wb = load_workbook(task.file_path)
    ws = wb.active
    headers = [cell.value for cell in ws[1]]
    order_no_index = headers.index("工单编号") + 1
    exported_order_nos = {ws.cell(row=row, column=order_no_index).value for row in range(2, ws.max_row + 1)}
    assert exported_order_nos == {"X1", "X2", "X3"}
    assert all(item.exported_at is not None for item in db.query(WorkOrder).all())
    from pathlib import Path

    Path(task.file_path).unlink(missing_ok=True)
    db.close()


def test_category_export_with_duplicate_identification_exports_original_rows_single_sheet(tmp_path):
    db = make_db()
    first = WorkOrder(order_no="P1", title="分类重复成员1", exported_at=datetime(2025, 1, 1))
    representative = WorkOrder(order_no="P2", title="分类重复代表")
    single = WorkOrder(order_no="P3", title="分类普通工单")
    hidden = WorkOrder(order_no="P4", title="已导出工单", exported_at=datetime(2025, 1, 1))
    db.add_all([first, representative, single, hidden])
    db.flush()
    cluster = EventCluster(cluster_key="cluster-p", title="分类重复代表", domain="安全生产", representative_order_id=representative.id, complaint_count=2)
    db.add(cluster)
    db.flush()
    db.add_all([ClusterMember(cluster_id=cluster.id, work_order_id=first.id), ClusterMember(cluster_id=cluster.id, work_order_id=representative.id)])
    for order in (first, representative, single, hidden):
        db.add(CaseClassification(work_order_id=order.id, module="public_interest", category="安全生产", priority="中", risk_score=3))
    db.commit()

    task = create_selected_export(
        db,
        "public_interest",
        "admin",
        module="public_interest",
        category="安全生产",
        identify_duplicates=True,
        hide_exported=True,
        duplicate_export_scope="representative",
    )

    from openpyxl import load_workbook

    wb = load_workbook(task.file_path)
    assert wb.sheetnames == ["导出结果"]
    ws = wb["导出结果"]
    headers = [cell.value for cell in ws[1]]
    assert headers[:4] == ["重复事件ID", "重复事件标题", "重复事件序号", "是否代表工单"]
    order_no_index = headers.index("工单编号") + 1
    exported_order_nos = [ws.cell(row=row, column=order_no_index).value for row in range(2, ws.max_row + 1)]
    assert exported_order_nos == ["P1", "P2", "P3"]
    cluster_id_index = headers.index("重复事件ID") + 1
    sequence_index = headers.index("重复事件序号") + 1
    representative_index = headers.index("是否代表工单") + 1
    assert [ws.cell(row=row, column=cluster_id_index).value for row in range(2, 5)] == [cluster.id, cluster.id, None]
    assert [ws.cell(row=row, column=sequence_index).value for row in range(2, 5)] == [1, 2, None]
    assert [ws.cell(row=row, column=representative_index).value for row in range(2, 5)] == ["否", "是", "否"]
    from pathlib import Path

    Path(task.file_path).unlink(missing_ok=True)
    db.close()


def test_category_export_with_duplicate_identification_includes_full_event_members(tmp_path):
    db = make_db()
    first = WorkOrder(order_no="M1", title="分类重复成员1")
    representative = WorkOrder(order_no="M2", title="分类重复代表")
    single = WorkOrder(order_no="M3", title="分类普通工单")
    db.add_all([first, representative, single])
    db.flush()
    cluster = EventCluster(cluster_key="cluster-m", title="分类重复代表", domain="安全生产", representative_order_id=representative.id, complaint_count=2)
    db.add(cluster)
    db.flush()
    db.add_all([ClusterMember(cluster_id=cluster.id, work_order_id=first.id), ClusterMember(cluster_id=cluster.id, work_order_id=representative.id)])
    db.add(CaseClassification(work_order_id=first.id, module="public_interest", category="安全生产", priority="中", risk_score=3))
    db.add(CaseClassification(work_order_id=single.id, module="public_interest", category="安全生产", priority="中", risk_score=3))
    db.commit()

    task = create_selected_export(
        db,
        "public_interest",
        "admin",
        module="public_interest",
        category="安全生产",
        identify_duplicates=True,
        duplicate_export_scope="all_members",
    )

    from openpyxl import load_workbook

    wb = load_workbook(task.file_path)
    assert wb.sheetnames == ["导出结果"]
    ws = wb["导出结果"]
    headers = [cell.value for cell in ws[1]]
    order_no_index = headers.index("工单编号") + 1
    exported_order_nos = [ws.cell(row=row, column=order_no_index).value for row in range(2, ws.max_row + 1)]
    assert exported_order_nos == ["M1", "M2", "M3"]
    cluster_id_index = headers.index("重复事件ID") + 1
    assert [ws.cell(row=row, column=cluster_id_index).value for row in range(2, 5)] == [cluster.id, cluster.id, None]
    from pathlib import Path

    Path(task.file_path).unlink(missing_ok=True)
    db.close()


def test_rebuild_clusters_extracts_specific_object_from_content():
    db = make_db()
    db.add_all(
        [
            WorkOrder(order_no="O1", title="食品问题", content="群众反映安心餐厅食品过期，孩子食用后腹泻。", problem_category="食品安全"),
            WorkOrder(order_no="O2", title="安心餐厅食品仍过期", content="多次投诉安心餐厅售卖过期食品，居民担心食品安全。", problem_category="食品安全"),
        ]
    )
    db.commit()

    created = rebuild_clusters(db)

    assert created == 1
    cluster = db.query(EventCluster).first()
    assert cluster.complaint_count == 2
    assert "安心餐厅" in cluster.match_reason
    db.close()


def test_rebuild_clusters_extracts_specific_road_address_from_content():
    db = make_db()
    db.add_all(
        [
            WorkOrder(order_no="RA1", title="餐饮食品过期", content="群众反映长阳镇稻田路8号安心餐厅售卖过期食品，孩子食用后腹泻。", problem_category="食品安全"),
            WorkOrder(order_no="RA2", title="安心餐厅食品仍过期", content="再次投诉稻田路8号安心餐厅售卖过期食品，居民担心食品安全。", problem_category="食品安全"),
        ]
    )
    db.commit()

    assert rebuild_clusters(db) == 1
    cluster = db.query(EventCluster).first()
    assert cluster.complaint_count == 2
    assert "稻田路8号" in cluster.match_reason or "安心餐厅" in cluster.match_reason
    db.close()


def test_rebuild_clusters_does_not_merge_same_community_different_issues():
    db = make_db()
    db.add_all(
        [
            WorkOrder(order_no="S1", title="幸福小区停车占道", content="幸福小区门口车辆占道影响通行。", location_point="幸福小区", problem_category="交通秩序"),
            WorkOrder(order_no="S2", title="幸福小区食品过期", content="幸福小区底商售卖过期食品。", location_point="幸福小区", problem_category="食品安全"),
        ]
    )
    db.commit()

    assert rebuild_clusters(db) == 0
    db.close()


def test_rebuild_clusters_does_not_merge_same_complainant_different_issues():
    db = make_db()
    db.add_all(
        [
            WorkOrder(order_no="C1", caller_phone="13800000000", title="停车收费争议", content="反映停车收费问题。", problem_category="停车"),
            WorkOrder(order_no="C2", caller_phone="13800000000", title="食品卫生问题", content="反映餐饮食品卫生问题。", problem_category="食品安全"),
        ]
    )
    db.commit()

    assert rebuild_clusters(db) == 0
    db.close()


def test_rebuild_clusters_handles_slight_company_name_variation():
    db = make_db()
    db.add_all(
        [
            WorkOrder(order_no="V1", company_name="北京安心餐饮有限公司", title="安心餐饮食品过期", content="购买食品发现过期。", problem_category="食品安全"),
            WorkOrder(order_no="V2", company_name="安心餐饮公司", title="安心餐饮售卖过期食品", content="再次发现该企业售卖过期食品。", problem_category="食品安全"),
        ]
    )
    db.commit()

    assert rebuild_clusters(db) == 1
    db.close()


def test_wage_rules_are_not_seeded_and_rule_api_rejects_wage_module():
    assert all(row["module"] != "wage" for row in seed_rule_rows())
    db = make_db()

    try:
        create_rule(
            payload=RuleCreateRequest(name="拖欠工资测试", module="wage", domain="拖欠工资", keywords="欠薪"),
            request=SimpleNamespace(client=SimpleNamespace(host="test")),
            db=db,
            user=SimpleNamespace(id=1, username="admin"),
        )
    except Exception as exc:
        assert getattr(exc, "status_code", None) == 400
    else:
        raise AssertionError("wage module should be rejected")
    db.close()


def test_batch_review_unknown_category_can_apply_to_cluster_members():
    db = make_db()
    first = WorkOrder(order_no="G1", title="其他分类成员1")
    representative = WorkOrder(order_no="G2", title="其他分类代表")
    db.add_all([first, representative])
    db.flush()
    cluster = EventCluster(cluster_key="cluster-g", title="其他分类代表", domain="其他", representative_order_id=representative.id, complaint_count=2)
    db.add(cluster)
    db.flush()
    db.add_all([ClusterMember(cluster_id=cluster.id, work_order_id=first.id), ClusterMember(cluster_id=cluster.id, work_order_id=representative.id)])
    first_vulnerable = CaseClassification(work_order_id=first.id, module="vulnerable", category="其他", priority="低", risk_score=1)
    representative_vulnerable = CaseClassification(work_order_id=representative.id, module="vulnerable", category="其他", priority="低", risk_score=1)
    administrative = CaseClassification(work_order_id=representative.id, module="administrative", category="其他", priority="低", risk_score=1)
    db.add_all([first_vulnerable, representative_vulnerable, administrative])
    db.commit()

    result = batch_review_classifications(
        payload=ClassificationBatchReviewRequest(classification_ids=[first_vulnerable.id], category="农民工", note="人工确认", apply_to_cluster=True),
        request=SimpleNamespace(client=SimpleNamespace(host="test")),
        db=db,
        user=SimpleNamespace(id=1, username="admin"),
    )

    assert result["updated"] == 2
    vulnerable_rows = db.query(CaseClassification).filter(CaseClassification.module == "vulnerable").all()
    assert {item.category for item in vulnerable_rows} == {"农民工"}
    assert all(item.review_status == "已确认" for item in vulnerable_rows)
    assert db.get(CaseClassification, administrative.id).category == "其他"
    db.close()


def test_selected_cluster_export_has_summary_and_member_sheets(tmp_path):
    db = make_db()
    db.add_all(
        [
            WorkOrder(order_no="C1", location_point="幸福小区", problem_category="供暖", title="幸福小区供暖不热", content="幸福小区2号楼供暖不热。"),
            WorkOrder(order_no="C2", location_point="幸福小区", problem_category="供暖", title="幸福小区供暖仍不热", content="幸福小区2号楼供暖不热，居民多次反映。"),
        ]
    )
    db.commit()
    rebuild_clusters(db)
    cluster = db.query(EventCluster).first()

    task = create_selected_export(db, "clusters_selected", "admin", cluster_ids=[cluster.id])

    from openpyxl import load_workbook
    wb = load_workbook(task.file_path)
    assert wb.sheetnames == ["事件汇总", "成员投诉"]
    assert wb["事件汇总"]["A1"].value == "屡诉未决事件ID"
    assert wb["成员投诉"].max_row == 3
    exported = [item.exported_at for item in db.query(WorkOrder).all()]
    assert all(exported)
    from pathlib import Path
    Path(task.file_path).unlink(missing_ok=True)
    db.close()


def test_alert_export_deduplicates_work_orders_to_representative_classification(tmp_path):
    db = make_db()
    order = WorkOrder(order_no="ALERT-DUP", title="同一工单多板块高风险")
    db.add(order)
    db.flush()
    db.add_all(
        [
            CaseClassification(work_order_id=order.id, module="public_interest", category="食品药品安全", priority="高", risk_score=8),
            CaseClassification(work_order_id=order.id, module="vulnerable", category="老人", priority="高", risk_score=9),
            CaseClassification(work_order_id=order.id, module="administrative", category="其他", priority="高", risk_score=7),
        ]
    )
    db.commit()

    task = create_selected_export(db, "alerts_selected", "admin", work_order_ids=[order.id])

    from openpyxl import load_workbook
    wb = load_workbook(task.file_path)
    ws = wb.active
    headers = [cell.value for cell in ws[1]]
    order_no_index = headers.index("工单编号") + 1
    module_index = headers.index("业务板块") + 1
    assert ws.max_row == 2
    assert ws.cell(row=2, column=order_no_index).value == "ALERT-DUP"
    assert ws.cell(row=2, column=module_index).value == "public_interest"
    from pathlib import Path
    Path(task.file_path).unlink(missing_ok=True)
    db.close()


def test_alert_export_duplicate_representative_includes_all_cluster_members(tmp_path):
    db = make_db()
    first = WorkOrder(order_no="ALERT-M1", title="重复预警成员")
    representative = WorkOrder(order_no="ALERT-M2", title="重复预警代表")
    db.add_all([first, representative])
    db.flush()
    cluster = EventCluster(cluster_key="cluster-alert-export", title="重复预警代表", domain="食品药品安全", representative_order_id=representative.id, complaint_count=2)
    db.add(cluster)
    db.flush()
    db.add_all([ClusterMember(cluster_id=cluster.id, work_order_id=first.id), ClusterMember(cluster_id=cluster.id, work_order_id=representative.id)])
    db.add(CaseClassification(work_order_id=first.id, module="public_interest", category="食品药品安全", priority="中", risk_score=4))
    db.add(CaseClassification(work_order_id=representative.id, module="public_interest", category="食品药品安全", priority="高", risk_score=8))
    db.commit()

    task = create_selected_export(
        db,
        "alerts_selected",
        "admin",
        work_order_ids=[representative.id],
        cluster_ids=[cluster.id],
        representative_work_order_ids=[representative.id],
        duplicate_export_scope="all_members",
        identify_duplicates=True,
    )

    from openpyxl import load_workbook
    wb = load_workbook(task.file_path)
    ws = wb.active
    headers = [cell.value for cell in ws[1]]
    order_no_index = headers.index("工单编号") + 1
    cluster_id_index = headers.index("重复事件ID") + 1
    exported_order_nos = [ws.cell(row=row, column=order_no_index).value for row in range(2, ws.max_row + 1)]
    assert exported_order_nos == ["ALERT-M1", "ALERT-M2"]
    assert [ws.cell(row=row, column=cluster_id_index).value for row in range(2, ws.max_row + 1)] == [cluster.id, cluster.id]
    assert all(item.exported_at is not None for item in db.query(WorkOrder).all())
    from pathlib import Path
    Path(task.file_path).unlink(missing_ok=True)
    db.close()


def test_cluster_intervention_assessment_uses_three_factors_for_initial_review():
    db = make_db()
    orders = [
        WorkOrder(order_no=f"R{index}", caller_phone="13800000000", location_point="同一工地", problem_category="安全生产", title="同一工地燃气泄漏隐患", content="同一工地燃气泄漏存在重大安全隐患，群众多次反映。", is_resolved="未解决", satisfaction="不满意")
        for index in range(1, 6)
    ]
    db.add_all(orders)
    db.flush()
    for order in orders:
        db.add(CaseClassification(work_order_id=order.id, module="public_interest", category="安全生产", priority="高", risk_score=8, rule_hits="燃气", evidence="重大安全隐患"))
    db.commit()
    rebuild_clusters(db)

    cluster = db.query(EventCluster).first()
    assessment = cluster_intervention_assessment(db, cluster)

    assert assessment["severity_level"] == "重点"
    assert assessment["intervention_advice"] == "建议初查"
    assert "反映次数5次" in assessment["assessment_reason"]
    db.close()


def test_cluster_intervention_assessment_recommends_immediate_intervention_for_long_unresolved():
    db = make_db()
    start = datetime.utcnow() - timedelta(days=95)
    orders = [
        WorkOrder(
            order_no=f"U{index}",
            caller_phone="13900000000",
            location_point="同一河道",
            problem_category="水污染",
            title="同一河道污水排放",
            content="群众反映同一河道污水排放长期未解决，影响公共环境。",
            is_resolved="未解决",
            satisfaction="不满意",
            closed_at=start + timedelta(days=index),
        )
        for index in range(10)
    ]
    db.add_all(orders)
    db.flush()
    for order in orders:
        db.add(CaseClassification(work_order_id=order.id, module="public_interest", category="生态环境和资源保护", priority="高", risk_score=8, rule_hits="污水", evidence="公共环境风险"))
    db.commit()
    rebuild_clusters(db)

    cluster = db.query(EventCluster).first()
    assessment = cluster_intervention_assessment(db, cluster)

    assert assessment["severity_level"] == "紧急"
    assert assessment["intervention_advice"] == "建议立即介入"
    assert "持续" in assessment["assessment_reason"]
    db.close()


def test_performance_and_trend_analysis_keep_table_results(tmp_path):
    db = make_db()
    order = WorkOrder(
        order_no="L1",
        host_unit="某执法局",
        town="长阳镇",
        problem_category="食品安全",
        title="小吃店食品过期",
        content="小吃店销售过期食品，多名群众反映腹泻。",
        handling_result="",
        reply_content="",
        is_resolved="未解决",
        satisfaction="不满意",
    )
    second = WorkOrder(
        order_no="L2",
        host_unit="某执法局",
        town="长阳镇",
        problem_category="食品安全",
        title="食品安全仍未解决",
        content="群众再次反映过期食品问题仍存在。",
        handling_result="",
        reply_content="",
        is_resolved="未解决",
        satisfaction="不满意",
    )
    db.add_all([order, second])
    db.flush()
    db.add(CaseClassification(work_order_id=order.id, module="public_interest", category="食品药品安全", priority="高", risk_score=7, rule_hits="食品", evidence="食品安全风险"))
    db.commit()

    perf = performance_anomalies(db, "host_unit", "month")
    trends = trend_analysis(db, "month", "category")

    assert perf and perf[0]["anomaly"]
    assert perf[0]["intervention_advice"] in {"建议关注", "暂不建议"}
    assert trends and trends[0]["name"] == "食品药品安全"
    db.close()
