import { useEffect, useMemo, useState } from "react";
import type { ChangeEvent, FormEvent, ReactNode } from "react";
import {
  BarChart3,
  Database,
  Download,
  FileSearch,
  Gavel,
  LogOut,
  Pencil,
  PlayCircle,
  Save,
  Search,
  Settings,
  ShieldCheck,
  Trash2,
  Upload,
  Users,
  X
} from "lucide-react";
import { api, getSession, setSession } from "./services/api";
import type { Classification, Cluster, DashboardSummary, DuplicateEvent, Page, PerformanceAnomaly, Session, TrendItem, WorkOrder } from "./types";

type View = "imports" | "dashboard" | "orders" | "publicInterest" | "vulnerable" | "administrative" | "labeling" | "analysis" | "admin";
type WorkOrderFilter = { title: string; isResolved?: string; refreshKey: number };
type ImportState = { message: string; busy: boolean; refreshKey: number; lastSuccess: boolean };
type LabelingContext = { module: string; returnView?: View };
type RuleFormState = { name: string; module: string; domain: string; keywords: string; weight: number; enabled: boolean };

const modules = {
  public_interest: { label: "公益成案领域", view: "publicInterest" as View },
  vulnerable: { label: "弱势群体", view: "vulnerable" as View },
  administrative: { label: "行政违法", view: "administrative" as View }
};

const navItems: Array<{ key: View; label: string; icon: typeof BarChart3 }> = [
  { key: "imports", label: "数据导入", icon: Upload },
  { key: "dashboard", label: "总览看板", icon: BarChart3 },
  { key: "orders", label: "工单库", icon: Database },
  { key: "publicInterest", label: "公益成案领域", icon: PlayCircle },
  { key: "vulnerable", label: "弱势群体", icon: Users },
  { key: "administrative", label: "行政违法", icon: Gavel },
  { key: "labeling", label: "线索标注", icon: FileSearch },
  { key: "analysis", label: "预警研判", icon: BarChart3 },
  { key: "admin", label: "系统管理", icon: Settings }
];

const publicInterestCategories = [
  "生态环境和资源保护",
  "食品药品安全",
  "国有财产保护",
  "国有土地使用权出让",
  "英烈保护",
  "未成年人保护",
  "军人地位和权益保障",
  "安全生产",
  "个人信息保护",
  "反电信网络诈骗",
  "无障碍环境建设",
  "文物和文化遗产保护",
  "农产品质量安全",
  "野生动物保护",
  "反垄断",
  "未知领域"
];

const vulnerableCategories = ["妇女", "儿童", "残疾人", "老人", "农民工", "其他"];
const administrativeCategories = ["小过重罚", "同案不同罚", "证据不足处罚", "未告知权利处罚", "未按程序处罚", "选择性执法", "重复处罚", "裁量失当处罚", "未考虑从轻情节处罚", "以罚代管", "其他"];

const moduleCategories: Record<string, string[]> = {
  public_interest: publicInterestCategories,
  vulnerable: vulnerableCategories,
  administrative: administrativeCategories
};

const workOrderSearchFields = [
  { value: "all", label: "全部字段" },
  { value: "order_no", label: "工单编号" },
  { value: "order_type", label: "工单类型" },
  { value: "title", label: "标题" },
  { value: "content", label: "主要内容" },
  { value: "problem_category", label: "问题分类" },
  { value: "tags", label: "标签" },
  { value: "status", label: "工单状态" },
  { value: "caller_name", label: "来电人" },
  { value: "caller_phone", label: "来电人电话/账号" },
  { value: "district", label: "被反映区" },
  { value: "town", label: "被反映街乡镇" },
  { value: "company_name", label: "企业名称" },
  { value: "host_unit", label: "主办单位" },
  { value: "community", label: "村/社区" },
  { value: "location_point", label: "小区点位" },
  { value: "handling_result", label: "办理结果" },
  { value: "reply_content", label: "回复内容" },
  { value: "handling_method", label: "处理受理方式" },
  { value: "order_nature", label: "工单性质" },
  { value: "is_resolved", label: "是否解决" },
  { value: "satisfaction", label: "是否满意" },
  { value: "extra_fields", label: "额外导入字段" }
];

function moduleLabel(value: string) {
  return modules[value as keyof typeof modules]?.label || value || "全部板块";
}

function normalizeLabelingModule(value?: string) {
  return value && moduleCategories[value] ? value : "public_interest";
}

function defaultRuleForm(module: string): RuleFormState {
  return { name: "", module, domain: moduleCategories[module]?.[0] || "", keywords: "", weight: 1, enabled: true };
}

function rulePayload(form: RuleFormState, module: string) {
  return { ...form, module, keywords: form.keywords.replace(/，/g, ","), weight: Number(form.weight) || 1 };
}

function keywordSummary(value: string) {
  const normalized = (value || "").replace(/，/g, ",").split(",").map((item) => item.trim()).filter(Boolean);
  const text = normalized.slice(0, 8).join("、");
  return normalized.length > 8 ? `${text} 等${normalized.length}项` : text || "未填写";
}

function Badge({ value }: { value?: string | null }) {
  const text = value || "未填";
  const className = text === "高" || text === "不满意" ? "danger" : text === "中" || text === "待确认" ? "warning" : "neutral";
  return <span className={`badge ${className}`}>{text}</span>;
}

function formatDateTime(value: unknown) {
  if (typeof value !== "string" || !/^\d{4}-\d{2}-\d{2}T/.test(value)) return "";
  const date = new Date(value);
  return Number.isNaN(date.getTime()) ? "" : date.toLocaleString();
}

function formatValue(value: unknown): string {
  if (value === null || value === undefined || value === "") return "未填写";
  if (typeof value === "boolean") return value ? "是" : "否";
  const dateText = formatDateTime(value);
  if (dateText) return dateText;
  if (Array.isArray(value)) return value.map((item) => (typeof item === "object" ? JSON.stringify(item) : String(item))).join("、") || "未填写";
  if (typeof value === "object") return JSON.stringify(value);
  return String(value);
}

function Login({ onLogin }: { onLogin: (session: Session) => void }) {
  const [username, setUsername] = useState("admin");
  const [password, setPassword] = useState("admin123");
  const [error, setError] = useState("");

  async function submit(event: FormEvent) {
    event.preventDefault();
    setError("");
    try {
      const session = await api.login(username, password);
      setSession(session);
      onLogin(session);
    } catch (err) {
      setError(err instanceof Error ? err.message : "登录失败");
    }
  }

  return (
    <main className="login-shell">
      <section className="login-panel">
        <div className="brand-mark"><Gavel size={28} /></div>
        <h1>12345涉检线索智能筛查工具</h1>
        <p>北京市房山区人民检察院 · 内部演示系统</p>
        <form onSubmit={submit} className="login-form">
          <label>账号<input value={username} onChange={(event) => setUsername(event.target.value)} /></label>
          <label>密码<input type="password" value={password} onChange={(event) => setPassword(event.target.value)} /></label>
          {error && <div className="error">{error}</div>}
          <button className="primary" type="submit"><ShieldCheck size={16} />登录工作台</button>
        </form>
        <div className="demo-accounts">演示账号：admin/admin123、prosecutor/prosecutor123、reviewer/reviewer123、viewer/viewer123</div>
      </section>
    </main>
  );
}

function Layout({ session, view, setView, children, onLogout }: { session: Session; view: View; setView: (view: View) => void; children: ReactNode; onLogout: () => void }) {
  return (
    <div className="app-shell">
      <aside className="sidebar">
        <div className="system-title">
          <Gavel size={24} />
          <div>
            <strong>涉检线索筛查</strong>
            <span>政法机关工作台</span>
          </div>
        </div>
        <nav>
          {navItems.map((item) => {
            const Icon = item.icon;
            return (
              <button key={item.key} className={view === item.key ? "active" : ""} onClick={() => setView(item.key)}>
                <Icon size={17} />{item.label}
              </button>
            );
          })}
        </nav>
      </aside>
      <main className="workspace">
        <header className="topbar">
          <div>
            <h1>{navItems.find((item) => item.key === view)?.label}</h1>
            <p>原始数据入库、筛查、查看、导出均保留完整内容，关键操作记录审计。</p>
          </div>
          <div className="user-box">
            <Users size={17} />
            <span>{session.display_name}</span>
            <small>{session.role}</small>
            <button className="icon-button" onClick={onLogout} title="退出登录"><LogOut size={16} /></button>
          </div>
        </header>
        {children}
      </main>
    </div>
  );
}

function EmptyState({ text = "暂无数据，请先在数据导入板块上传 Excel。" }: { text?: string }) {
  return <div className="empty-state">{text}</div>;
}

function Stat({ label, value, tone = "", onClick }: { label: string; value: number | string; tone?: string; onClick?: () => void }) {
  const content = <><span>{label}</span><strong>{value}</strong></>;
  if (onClick) {
    return <button className={`stat stat-button ${tone}`} onClick={onClick} type="button">{content}</button>;
  }
  return <div className={`stat ${tone}`}>{content}</div>;
}

function DetailField({ label, value }: { label: string; value: unknown }) {
  return <span><strong>{label}：</strong>{formatValue(value)}</span>;
}

function WorkOrderDetailPanel({ selected }: { selected: any | null }) {
  if (!selected) return null;
  const extraFields = Array.isArray(selected.extra_fields) ? selected.extra_fields : [];
  const classifications = Array.isArray(selected.classifications) ? selected.classifications : [];
  const fields: Array<[string, unknown]> = [
    ["系统ID", selected.id],
    ["导入批次", selected.batch_id],
    ["工单编号", selected.order_no],
    ["工单类型", selected.order_type],
    ["工单状态", selected.status],
    ["问题分类", selected.problem_category],
    ["标签", selected.tags],
    ["被反映区", selected.district],
    ["街乡镇", selected.town],
    ["村/社区", selected.community],
    ["小区点位", selected.location_point],
    ["企业名称", selected.company_name],
    ["来电人", selected.caller_name],
    ["来电人电话/账号", selected.caller_phone],
    ["处理受理方式", selected.handling_method],
    ["主办单位", selected.host_unit],
    ["办结时间", selected.closed_at],
    ["工单性质", selected.order_nature],
    ["是否解决", selected.is_resolved],
    ["是否满意", selected.satisfaction],
    ["公益成案领域", selected.case_domain],
    ["已导出", selected.exported_at ? "是" : "否"],
    ["导出时间", selected.exported_at],
    ["导出人", selected.exported_by],
    ["导出来源", selected.export_context],
    ["入库时间", selected.created_at]
  ];
  return (
    <section className="panel detail">
      <h2>数据完整信息：{selected.title || selected.order_no || "未命名工单"}</h2>
      <div className="detail-grid">
        {fields.map(([label, value]) => <DetailField key={label} label={label} value={value} />)}
      </div>
      <h3>主要内容</h3>
      <p>{selected.content || "暂无内容"}</p>
      <h3>办理结果</h3>
      <p>{selected.handling_result || "暂无办理结果"}</p>
      {selected.reply_content && <><h3>回复内容</h3><p>{selected.reply_content}</p></>}
      {classifications.length > 0 && (
        <>
          <h3>筛查分类结果</h3>
          <div className="classification-list">
            {classifications.map((item: any) => (
              <div className="evidence-box" key={item.id}>
                <strong>{moduleLabel(item.module)} · {item.category}</strong>
                <span>风险：{item.priority} · 状态：{item.review_status}</span>
                <p>{item.evidence}</p>
                {item.rule_hits && <p>线索标注命中：{item.rule_hits}</p>}
              </div>
            ))}
          </div>
        </>
      )}
      {extraFields.length > 0 && (
        <>
          <h3>额外导入字段</h3>
          <div className="detail-grid record-detail-grid">
            {extraFields.map((field: any, index: number) => (
              <DetailField key={`${field.name}-${index}`} label={field.name || `额外字段${index + 1}`} value={field.value} />
            ))}
          </div>
        </>
      )}
    </section>
  );
}

function RecordDetailPanel({ title, record }: { title: string; record: Record<string, unknown> | null }) {
  if (!record) return null;
  return (
    <section className="panel detail">
      <h2>{title}</h2>
      <div className="detail-grid record-detail-grid">
        {Object.entries(record).map(([key, value]) => <DetailField key={key} label={key} value={value} />)}
      </div>
    </section>
  );
}

function DuplicateEventButton({ event, onOpen }: { event?: DuplicateEvent | null; onOpen: (event: DuplicateEvent) => void }) {
  if (!event) return <span className="muted">无</span>;
  return (
    <button className="link-button event-chip" type="button" onClick={(clickEvent) => { clickEvent.stopPropagation(); onOpen(event); }}>
      事件{event.cluster_id} · {event.complaint_count}件
    </button>
  );
}

function DuplicateEventPanel({
  cluster,
  selectedMember,
  onOpenMember
}: {
  cluster: any | null;
  selectedMember: any | null;
  onOpenMember: (id: number) => void;
}) {
  const [exportMessage, setExportMessage] = useState("");
  if (!cluster) return null;
  async function exportCluster() {
    await exportAndDownload({ export_type: "clusters_selected", cluster_ids: [cluster.id] });
    setExportMessage("该重复事件已导出，事件下全部投诉已标记为已导出。");
  }
  return (
    <section className="panel detail duplicate-detail">
      <div className="detail-heading">
        <h2>重复事件：{cluster.title}</h2>
        <button className="primary" onClick={exportCluster}><Download size={15} />导出该重复事件</button>
      </div>
      {exportMessage && <div className="notice compact-notice">{exportMessage}</div>}
      <div className="detail-grid">
        <DetailField label="事件ID" value={cluster.id} />
        <DetailField label="代表工单" value={cluster.representative_order?.order_no || cluster.representative_order_id} />
        <DetailField label="投诉次数" value={cluster.complaint_count} />
        <DetailField label="持续天数" value={cluster.duration_days} />
        <DetailField label="风险等级" value={cluster.risk_level} />
        <DetailField label="严重程度" value={cluster.severity_level} />
        <DetailField label="介入建议" value={cluster.intervention_advice} />
        <DetailField label="街乡镇" value={cluster.town} />
        <DetailField label="点位" value={cluster.location_point} />
      </div>
      <h3>识别理由</h3>
      <p>{cluster.match_reason || "同一具体对象，问题分类和标题/内容高度相近。"}</p>
      <h3>评估理由</h3>
      <p>{cluster.assessment_reason || "未触发履职异常三要素评估。"}</p>
      {cluster.representative_order && (
        <>
          <h3>代表事件</h3>
          <div className="representative-card clickable" onClick={() => onOpenMember(cluster.representative_order.id)}>
            <strong>{cluster.representative_order.order_no || "未填写编号"}</strong>
            <span>{cluster.representative_order.title || "未填写标题"}</span>
          </div>
        </>
      )}
      <h3>全部投诉</h3>
      <div className="table-panel embedded-table">
        <table>
          <thead><tr><th>序号</th><th>编号</th><th>标题</th><th>分类</th><th>解决</th><th>满意度</th><th>点位</th></tr></thead>
          <tbody>
            {(cluster.members || []).map((item: WorkOrder, index: number) => (
              <tr key={item.id} className={`clickable ${selectedMember?.id === item.id ? "selected-row" : ""}`} onClick={() => onOpenMember(item.id)}>
                <td>{index + 1}</td><td>{item.order_no}</td><td>{item.title}</td><td>{item.problem_category}</td><td><Badge value={item.is_resolved} /></td><td><Badge value={item.satisfaction} /></td><td>{item.location_point}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </section>
  );
}

async function exportAndDownload(body: Record<string, unknown>) {
  const task = await api.createSelectedExport(body) as any;
  await api.downloadExport(task.id, task.file_path);
}

function duplicateAwareExportBody(base: Record<string, unknown>, rows: Array<WorkOrder | Classification>) {
  const representativeRows = rows.filter((item) => item.is_duplicate_representative && item.cluster_id);
  return {
    ...base,
    work_order_ids: rows.map((item) => ("work_order_id" in item ? item.work_order_id : item.id)),
    representative_work_order_ids: representativeRows.map((item) => ("work_order_id" in item ? item.work_order_id : item.id)),
    cluster_ids: Array.from(new Set(representativeRows.map((item) => item.cluster_id).filter((id): id is number => typeof id === "number"))),
    duplicate_export_scope: representativeRows.length > 0 ? "all_members" : "representative",
    identify_duplicates: Boolean(base.identify_duplicates) || representativeRows.length > 0
  };
}

function categoryExportBody(base: Record<string, unknown>, identifyDuplicates: boolean) {
  return {
    ...base,
    identify_duplicates: identifyDuplicates,
    duplicate_export_scope: identifyDuplicates ? "all_members" : "representative"
  };
}

function Dashboard({ openWorkOrders, openAnalysis }: { openWorkOrders: (filter: Omit<WorkOrderFilter, "refreshKey">) => void; openAnalysis: () => void }) {
  const [data, setData] = useState<DashboardSummary | null>(null);
  const [townPage, setTownPage] = useState<Page<WorkOrder> | null>(null);
  const [drillTitle, setDrillTitle] = useState("");
  const [selectedDetail, setSelectedDetail] = useState<any | null>(null);
  const [selectedAudit, setSelectedAudit] = useState<Record<string, unknown> | null>(null);
  useEffect(() => {
    api.dashboard().then((res) => setData(res as DashboardSummary));
  }, []);
  async function openTown(name: string) {
    const page = await api.workOrders(`?page_size=1000&town=${encodeURIComponent(name === "未填写" ? "__EMPTY__" : name)}`) as Page<WorkOrder>;
    setDrillTitle(`${name} · 共 ${page.total} 条`);
    setTownPage(page);
    setSelectedDetail(null);
    setSelectedAudit(null);
  }
  if (!data) return <div className="panel">正在加载总览数据...</div>;
  return (
    <div className="stack">
      <section className="stats-grid">
        <Stat label="工单总数" value={data.work_orders} onClick={() => openWorkOrders({ title: "全部工单" })} />
        <Stat label="高风险" value={data.high_risk} tone="danger-bg" onClick={openAnalysis} />
        <Stat label="屡诉未决" value={data.clusters} onClick={openAnalysis} />
        <Stat label="未解决工单" value={data.unresolved} onClick={() => openWorkOrders({ title: "未解决工单", isResolved: "未解决" })} />
      </section>
      <section className="panel">
        <h2>街乡镇分布</h2>
        {data.town_distribution.length === 0 && <EmptyState />}
        {data.town_distribution.map((item) => (
          <div className="metric-row clickable" key={item.name} onClick={() => openTown(item.name)}>
            <span>{item.name}</span>
            <strong>{item.value}</strong>
          </div>
        ))}
      </section>
      {townPage && (
        <section className="panel table-panel">
          <h2>街乡镇工单明细：{drillTitle}</h2>
          <table>
            <thead><tr><th>序号</th><th>编号</th><th>标题</th><th>分类</th><th>解决</th><th>满意度</th><th>已导出</th></tr></thead>
            <tbody>
              {townPage.items.map((item, index) => (
                <tr key={item.id} className={`clickable ${selectedDetail?.id === item.id ? "selected-row" : ""}`} onClick={async () => setSelectedDetail(await api.workOrder(item.id))}>
                  <td>{index + 1}</td>
                  <td>{item.order_no}</td>
                  <td>{item.title}</td>
                  <td>{item.problem_category}</td>
                  <td><Badge value={item.is_resolved} /></td>
                  <td><Badge value={item.satisfaction} /></td>
                  <td>{item.exported_at ? "是" : "否"}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </section>
      )}
      <WorkOrderDetailPanel selected={selectedDetail} />
      <section className="panel table-panel">
        <h2>近期审计</h2>
        <table>
          <thead><tr><th>序号</th><th>用户</th><th>动作</th><th>说明</th><th>时间</th></tr></thead>
          <tbody>
            {data.recent_audits.map((item, index) => (
              <tr key={item.id} className={`clickable ${selectedAudit?.id === item.id ? "selected-row" : ""}`} onClick={() => { setSelectedAudit(item as Record<string, unknown>); setSelectedDetail(null); }}>
                <td>{index + 1}</td>
                <td>{item.username}</td>
                <td>{item.action}</td>
                <td>{item.detail}</td>
                <td>{new Date(item.created_at).toLocaleString()}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </section>
      <RecordDetailPanel title="审计记录完整信息" record={selectedAudit} />
    </div>
  );
}

function Imports({
  importState,
  setImportState,
  session
}: {
  importState: ImportState;
  setImportState: (value: ImportState | ((prev: ImportState) => ImportState)) => void;
  session: Session;
}) {
  const [rows, setRows] = useState<any[]>([]);
  const [selectedIds, setSelectedIds] = useState<number[]>([]);
  const [selectedImport, setSelectedImport] = useState<Record<string, unknown> | null>(null);
  const [screeningBusy, setScreeningBusy] = useState(false);
  const permissions = Array.isArray(session.permissions) ? session.permissions : [];
  const canImport = permissions.includes("all") || permissions.includes("import");
  const refresh = () => api.imports().then((res) => setRows(res as any[]));
  useEffect(() => { refresh(); }, [importState.refreshKey]);

  async function upload(event: ChangeEvent<HTMLInputElement>) {
    const input = event.currentTarget;
    const files = Array.from(event.target.files || []);
    if (files.length === 0) return;
    if (!canImport) {
      setImportState((prev) => ({ ...prev, lastSuccess: false, message: "当前账号没有数据导入权限，请使用 admin 账号或联系管理员授权。" }));
      input.value = "";
      return;
    }
    setImportState((prev) => ({ ...prev, busy: true, message: `正在导入 ${files.length} 个文件。` }));
    try {
      const results = [];
      for (const file of files) {
        results.push(await api.uploadImport(file) as any);
      }
      const successRows = results.reduce((sum, item) => sum + Number(item.success_rows || 0), 0);
      setImportState({ busy: false, refreshKey: Date.now(), lastSuccess: successRows > 0, message: `导入完成：新增 ${successRows} 条工单。请勾选批次后运行筛查。` });
    } catch (err) {
      setImportState({ busy: false, refreshKey: Date.now(), lastSuccess: false, message: err instanceof Error ? `上传未完成：${err.message}` : "上传未完成，请稍后重试。" });
    } finally {
      input.value = "";
    }
  }

  function toggle(id: number) {
    setSelectedIds((prev) => prev.includes(id) ? prev.filter((item) => item !== id) : [...prev, id]);
  }

  async function runSelectedScreening() {
    const targetIds = selectedIds.length ? selectedIds : rows.filter((row) => row.status === "success").map((row) => row.id);
    if (targetIds.length === 0) {
      setImportState((prev) => ({ ...prev, message: "请先上传成功批次后再运行筛查。" }));
      return;
    }
    setScreeningBusy(true);
    try {
      const result = await api.runScreening({ batch_ids: targetIds, modules: ["public_interest", "vulnerable", "administrative"] }) as any;
      const moduleText = Array.isArray(result.modules) && result.modules.length > 0 ? result.modules.map(moduleLabel).join("、") : "公益成案领域、弱势群体、行政违法";
      setImportState((prev) => ({ ...prev, lastSuccess: true, refreshKey: Date.now(), message: `筛查完成：处理工单 ${result.processed ?? result.classified_work_orders ?? 0} 条，已生成${moduleText}筛查结果。` }));
    } finally {
      setScreeningBusy(false);
    }
  }

  async function deleteSelected() {
    if (selectedIds.length === 0) return;
    if (!window.confirm(`确认删除 ${selectedIds.length} 个导入批次及对应工单、分类和聚合结果？`)) return;
    for (const id of selectedIds) {
      await api.deleteImport(id);
    }
    setSelectedIds([]);
    setSelectedImport(null);
    setImportState((prev) => ({ ...prev, refreshKey: Date.now(), message: "已删除选中导入批次。" }));
  }

  return (
    <div className="stack">
      <section className="panel toolbar">
        <label className={`file-button ${importState.busy || !canImport ? "disabled" : ""}`}>
          <Upload size={16} />{importState.busy ? "导入中" : "上传 Excel"}
          <input type="file" multiple accept=".xlsx,.xls,.xlsm,.csv" onChange={upload} disabled={importState.busy || !canImport} />
        </label>
        <button className="primary" onClick={runSelectedScreening} disabled={screeningBusy}><PlayCircle size={16} />{screeningBusy ? "筛查中" : "运行智能筛查"}</button>
        <button className="danger-button" onClick={deleteSelected} disabled={selectedIds.length === 0}><Trash2 size={15} />删除选中批次</button>
        <span>{importState.message}</span>
      </section>
      <section className="panel table-panel">
        <h2>导入批次</h2>
        <table>
          <thead><tr><th><input type="checkbox" checked={rows.length > 0 && selectedIds.length === rows.length} onChange={(event) => setSelectedIds(event.target.checked ? rows.map((row) => row.id) : [])} /></th><th>序号</th><th>文件</th><th>状态</th><th>总行数</th><th>成功</th><th>失败</th><th>导入人</th><th>时间</th></tr></thead>
          <tbody>
            {rows.map((row, index) => (
              <tr key={row.id} className={`clickable ${selectedImport?.id === row.id ? "selected-row" : ""}`} onClick={() => setSelectedImport(row as Record<string, unknown>)}>
                <td onClick={(event) => event.stopPropagation()}><input type="checkbox" checked={selectedIds.includes(row.id)} onChange={() => toggle(row.id)} /></td>
                <td>{index + 1}</td>
                <td>{row.filename}</td>
                <td><Badge value={row.status} /></td>
                <td>{row.total_rows}</td>
                <td>{row.success_rows}</td>
                <td>{row.failed_rows}</td>
                <td>{row.imported_by}</td>
                <td>{new Date(row.created_at).toLocaleString()}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </section>
      <RecordDetailPanel title="导入批次完整信息" record={selectedImport} />
    </div>
  );
}

function WorkOrders({ filter }: { filter: WorkOrderFilter }) {
  const [page, setPage] = useState<Page<WorkOrder> | null>(null);
  const [currentPage, setCurrentPage] = useState(1);
  const [query, setQuery] = useState("");
  const [searchField, setSearchField] = useState("content");
  const [searchMode, setSearchMode] = useState("semantic");
  const [hideExported, setHideExported] = useState(false);
  const [identifyDuplicates, setIdentifyDuplicates] = useState(false);
  const [selectedIds, setSelectedIds] = useState<number[]>([]);
  const [selected, setSelected] = useState<any | null>(null);
  const [duplicateCluster, setDuplicateCluster] = useState<any | null>(null);
  const [duplicateMember, setDuplicateMember] = useState<any | null>(null);
  const [message, setMessage] = useState("");

  const load = (nextPage = currentPage) => {
    const params = new URLSearchParams({ page: String(nextPage), page_size: "80", q: query, search_field: searchField, search_mode: searchMode });
    if (filter.isResolved) params.set("is_resolved", filter.isResolved);
    if (hideExported) params.set("hide_exported", "true");
    if (identifyDuplicates) params.set("identify_duplicates", "true");
    return api.workOrders(`?${params.toString()}`).then((res) => {
      setCurrentPage(nextPage);
      setPage(res as Page<WorkOrder>);
      setSelectedIds([]);
    });
  };
  useEffect(() => { setSelected(null); setDuplicateCluster(null); setDuplicateMember(null); load(1); }, [filter.refreshKey, hideExported, identifyDuplicates]);

  function toggle(id: number) {
    setSelectedIds((prev) => prev.includes(id) ? prev.filter((item) => item !== id) : [...prev, id]);
  }

  async function exportSelected(type: "wage" | "work_orders") {
    if (selectedIds.length === 0) {
      setMessage("请先勾选要导出的工单。");
      return;
    }
    const rows = (page?.items || []).filter((item) => selectedIds.includes(item.id));
    await exportAndDownload(duplicateAwareExportBody({ export_type: type }, rows));
    setMessage(type === "wage" ? "拖欠工资核心内容提炼已导出，相关工单已标记为已导出。" : "选中工单已导出并标记。");
    await load(currentPage);
  }

  async function openDuplicate(event: DuplicateEvent) {
    setDuplicateMember(null);
    setDuplicateCluster(await api.clusterDetail(event.cluster_id));
  }

  async function openDuplicateMember(id: number) {
    const detail = await api.workOrder(id);
    setDuplicateMember(detail);
    setSelected(detail);
  }

  async function openRow(item: WorkOrder) {
    if (identifyDuplicates && item.is_duplicate_representative && item.duplicate_event) {
      setSelected(null);
      await openDuplicate(item.duplicate_event);
      return;
    }
    setSelected(await api.workOrder(item.id));
  }

  return (
    <div className="stack workbench-page orders-workbench">
      {message && <div className="notice">{message}</div>}
      <section className="panel toolbar workbench-toolbar">
        <div className="toolbar-group">
          <label className="compact-field">检索字段<select value={searchField} onChange={(event) => setSearchField(event.target.value)}>{workOrderSearchFields.map((item) => <option key={item.value} value={item.value}>{item.label}</option>)}</select></label>
          <label className="compact-field">检索方式<select value={searchMode} onChange={(event) => setSearchMode(event.target.value)}><option value="keyword">关键词检索</option><option value="semantic">语义检索</option></select></label>
          <div className="searchbox"><Search size={16} /><input placeholder="可输入：拖欠工资、欠薪、包工头等" value={query} onChange={(event) => setQuery(event.target.value)} onKeyDown={(event) => event.key === "Enter" && load(1)} /></div>
          <button onClick={() => load(1)}>查询</button>
        </div>
        <div className="toolbar-group">
          <label className="checkbox inline-checkbox"><input type="checkbox" checked={hideExported} onChange={(event) => setHideExported(event.target.checked)} />去除已导出</label>
          <label className="checkbox inline-checkbox"><input type="checkbox" checked={identifyDuplicates} onChange={(event) => setIdentifyDuplicates(event.target.checked)} />识别重复事件</label>
        </div>
        <div className="toolbar-group toolbar-actions">
          <button className="primary" onClick={() => exportSelected("wage")}><Download size={15} />导出拖欠工资提炼</button>
          <button onClick={() => exportSelected("work_orders")}><Download size={15} />导出选中原始数据</button>
        </div>
        <span className="toolbar-note">疑似拖欠工资、欠薪、农民工讨薪数据可使用专项提炼导出。</span>
        {identifyDuplicates && <span className="toolbar-note">去除已导出仅过滤入口数据；重复事件命中后，导出会完整包含全部成员并相邻排列。</span>}
      </section>
      <section className="panel table-panel workbench-table-panel">
        <h2>{filter.title}</h2>
        <div className="table-summary">共 {page?.total ?? 0} 条，已选 {selectedIds.length} 条。</div>
        <table>
          <thead><tr><th><input type="checkbox" checked={(page?.items.length || 0) > 0 && selectedIds.length === page?.items.length} onChange={(event) => setSelectedIds(event.target.checked ? (page?.items || []).map((item) => item.id) : [])} /></th>{identifyDuplicates && <th>重复事件</th>}<th>序号</th><th>编号</th><th>标题</th><th>分类</th><th>街乡镇</th><th>解决</th><th>满意度</th><th>已导出</th></tr></thead>
          <tbody>
            {page?.items.map((item, index) => (
              <tr key={`${item.id}-${item.cluster_id || "single"}`} className={`clickable ${selected?.id === item.id ? "selected-row" : ""}`} onClick={() => openRow(item)}>
                <td onClick={(event) => event.stopPropagation()}><input type="checkbox" checked={selectedIds.includes(item.id)} onChange={() => toggle(item.id)} /></td>
                {identifyDuplicates && <td><DuplicateEventButton event={item.duplicate_event} onOpen={openDuplicate} /></td>}
                <td>{(currentPage - 1) * (page?.page_size ?? 80) + index + 1}</td>
                <td>{item.order_no}</td>
                <td>{item.title}</td>
                <td>{item.problem_category}</td>
                <td>{item.town}</td>
                <td><Badge value={item.is_resolved} /></td>
                <td><Badge value={item.satisfaction} /></td>
                <td>{item.exported_at ? "是" : "否"}</td>
              </tr>
            ))}
          </tbody>
        </table>
        {page?.items.length === 0 && <EmptyState />}
      </section>
      <DuplicateEventPanel cluster={duplicateCluster} selectedMember={duplicateMember} onOpenMember={openDuplicateMember} />
      <section className="panel pager">
        <button disabled={currentPage <= 1} onClick={() => load(currentPage - 1)}>上一页</button>
        <button disabled={!page || currentPage * page.page_size >= page.total} onClick={() => load(currentPage + 1)}>下一页</button>
      </section>
      <WorkOrderDetailPanel selected={selected} />
    </div>
  );
}

function ClassificationPage({ module, title, openLabeling }: { module: string; title: string; openLabeling: (module: string, returnView: View) => void }) {
  const [categories, setCategories] = useState<Array<{ name: string; value: number }>>([]);
  const [selectedCategory, setSelectedCategory] = useState(moduleCategories[module]?.[0] || "");
  const [page, setPage] = useState<Page<Classification> | null>(null);
  const [hideExported, setHideExported] = useState(false);
  const [identifyDuplicates, setIdentifyDuplicates] = useState(false);
  const [selectedIds, setSelectedIds] = useState<number[]>([]);
  const [selectedItem, setSelectedItem] = useState<Classification | null>(null);
  const [selectedDetail, setSelectedDetail] = useState<any | null>(null);
  const [duplicateCluster, setDuplicateCluster] = useState<any | null>(null);
  const [duplicateMember, setDuplicateMember] = useState<any | null>(null);
  const [reviewCategory, setReviewCategory] = useState("");
  const [reviewNote, setReviewNote] = useState("");
  const [batchReviewCategory, setBatchReviewCategory] = useState("");
  const [batchReviewNote, setBatchReviewNote] = useState("");
  const [rowReviewCategories, setRowReviewCategories] = useState<Record<number, string>>({});
  const [message, setMessage] = useState("");
  const reviewableCategory = selectedCategory === "其他" || selectedCategory === "未知领域";
  const availableReviewCategories = categories.map((item) => item.name).filter((name) => name !== "其他" && name !== "未知领域" && name !== "未分类");

  async function loadCategories(preferred = selectedCategory) {
    const params = new URLSearchParams({ module });
    if (hideExported) params.set("hide_exported", "true");
    const res = await api.classificationCategories(`?${params.toString()}`) as Array<{ name: string; value: number }>;
    const known = moduleCategories[module] || [];
    const merged = [...known.map((name) => ({ name, value: res.find((item) => item.name === name)?.value || 0 })), ...res.filter((item) => !known.includes(item.name))];
    setCategories(merged);
    const next = merged.some((item) => item.name === preferred) ? preferred : merged[0]?.name || "";
    setSelectedCategory(next);
    return next;
  }

  async function loadCategory(category = selectedCategory) {
    const params = new URLSearchParams({ module, category, page_size: "500" });
    if (hideExported) params.set("hide_exported", "true");
    if (identifyDuplicates) params.set("identify_duplicates", "true");
    const res = await api.classifications(`?${params.toString()}`) as Page<Classification>;
    setPage(res);
    setSelectedIds([]);
    setSelectedItem(null);
    setSelectedDetail(null);
    setDuplicateCluster(null);
    setDuplicateMember(null);
    setRowReviewCategories({});
  }

  useEffect(() => {
    loadCategories().then((category) => loadCategory(category));
  }, [module, hideExported, identifyDuplicates]);

  async function openCategory(category: string) {
    setSelectedCategory(category);
    await loadCategory(category);
  }

  async function openItem(item: Classification) {
    setSelectedItem(item);
    setSelectedDetail(await api.workOrder(item.work_order_id));
    setReviewCategory((item.category === "其他" || item.category === "未知领域") ? (availableReviewCategories[0] || "") : item.category);
    setReviewNote("");
  }

  function toggle(id: number) {
    setSelectedIds((prev) => prev.includes(id) ? prev.filter((item) => item !== id) : [...prev, id]);
  }

  async function confirmSelected() {
    if (!selectedItem) return;
    await api.reviewClassification(selectedItem.id, { predicted_domain: reviewCategory, review_status: "已确认", priority: selectedItem.priority, note: reviewNote || `确认分类为${reviewCategory}`, apply_to_cluster: true });
    setMessage("分类已人工确认保存。");
    await loadCategories(reviewCategory);
    await loadCategory(reviewCategory);
  }

  async function confirmRow(item: Classification) {
    const category = rowReviewCategories[item.id] || availableReviewCategories[0] || "";
    if (!category) {
      setMessage("没有可确认的分类，请先在线索标注中维护分类。");
      return;
    }
    await api.reviewClassification(item.id, { predicted_domain: category, review_status: "已确认", priority: item.priority, note: `行内确认分类为${category}`, apply_to_cluster: true });
    setMessage(`已确认分类为${category}。`);
    await loadCategories(category);
    await loadCategory(selectedCategory);
  }

  async function batchConfirmSelected() {
    const selectedRows = (page?.items || []).filter((item) => selectedIds.includes(item.work_order_id));
    const category = batchReviewCategory || availableReviewCategories[0] || "";
    if (selectedRows.length === 0) {
      setMessage("请先勾选要批量确认的数据。");
      return;
    }
    if (!category) {
      setMessage("没有可确认的分类，请先在线索标注中维护分类。");
      return;
    }
    await api.batchReviewClassifications({ classification_ids: selectedRows.map((item) => item.id), category, note: batchReviewNote || `批量确认分类为${category}`, apply_to_cluster: true });
    setMessage(`已批量确认 ${selectedRows.length} 条代表数据，重复事件成员已同步更新。`);
    setSelectedIds([]);
    await loadCategories(category);
    await loadCategory(selectedCategory);
  }

  async function exportRows(scope: "selected" | "category") {
    if (scope === "category") {
      if (!page || page.total === 0) {
        setMessage("当前分类没有可导出的数据。");
        return;
      }
      await exportAndDownload(categoryExportBody({ export_type: module, module, category: selectedCategory, hide_exported: hideExported }, identifyDuplicates));
      setMessage(identifyDuplicates ? "当前分类已导出：重复事件全部投诉已相邻展开，相关工单已标记为已导出。" : "当前分类已导出，相关工单已标记为已导出。");
      await loadCategory(selectedCategory);
      return;
    }
    const rows = (page?.items || []).filter((item) => selectedIds.includes(item.work_order_id));
    if (rows.length === 0) {
      setMessage("请先勾选要导出的数据。");
      return;
    }
    await exportAndDownload(duplicateAwareExportBody({ export_type: module, module, category: selectedCategory }, rows));
    setMessage(identifyDuplicates ? "导出完成：选中重复事件的全部投诉已相邻展开，相关工单已标记为已导出。" : "导出完成，相关工单已标记为已导出。");
    await loadCategory(selectedCategory);
  }

  async function exportWageRows() {
    if (selectedIds.length === 0) {
      setMessage("请先勾选涉及拖欠工资、欠薪或农民工讨薪的数据。");
      return;
    }
    const rows = (page?.items || []).filter((item) => selectedIds.includes(item.work_order_id));
    await exportAndDownload(duplicateAwareExportBody({ export_type: "wage" }, rows));
    setMessage("拖欠工资核心内容提炼已导出，相关工单已标记为已导出。");
    await loadCategory(selectedCategory);
  }

  async function openDuplicate(event: DuplicateEvent) {
    setDuplicateMember(null);
    setDuplicateCluster(await api.clusterDetail(event.cluster_id));
  }

  async function openDuplicateMember(id: number) {
    const detail = await api.workOrder(id);
    setDuplicateMember(detail);
    setSelectedDetail(detail);
  }

  async function openClassificationRow(item: Classification) {
    setSelectedItem(item);
    setReviewCategory((item.category === "其他" || item.category === "未知领域") ? (availableReviewCategories[0] || "") : item.category);
    setReviewNote("");
    if (identifyDuplicates && item.is_duplicate_representative && item.duplicate_event) {
      setSelectedDetail(null);
      await openDuplicate(item.duplicate_event);
      return;
    }
    setSelectedDetail(await api.workOrder(item.work_order_id));
  }

  return (
    <div className="stack workbench-page classification-page">
      {message && <div className="notice">{message}</div>}
      <section className="panel toolbar workbench-toolbar">
        <div className="toolbar-group">
          <label className="checkbox inline-checkbox"><input type="checkbox" checked={hideExported} onChange={(event) => setHideExported(event.target.checked)} />去除已导出</label>
          <label className="checkbox inline-checkbox"><input type="checkbox" checked={identifyDuplicates} onChange={(event) => setIdentifyDuplicates(event.target.checked)} />识别重复事件</label>
        </div>
        <div className="toolbar-group toolbar-actions">
          <button className="primary" onClick={() => exportRows("selected")}><Download size={15} />导出选中</button>
          <button onClick={() => exportRows("category")}><Download size={15} />导出当前分类</button>
          {module === "vulnerable" && <button onClick={exportWageRows}><Download size={15} />导出拖欠工资提炼</button>}
        </div>
        <span>当前板块：{title}。点击分类查看对应投诉，点击单条查看完整原始内容。</span>
        {identifyDuplicates && <span className="toolbar-note">去除已导出仅过滤入口数据；重复事件命中后，导出会完整包含全部成员并相邻排列。</span>}
        {module === "vulnerable" && <span className="toolbar-note">农民工欠薪等弱势群体线索可勾选后生成拖欠工资专项提炼。</span>}
      </section>
      {reviewableCategory && (
        <section className="panel toolbar workbench-toolbar compact-review-toolbar">
          <label className="compact-field">批量确认分类<select value={batchReviewCategory} onChange={(event) => setBatchReviewCategory(event.target.value)}><option value="">请选择分类</option>{availableReviewCategories.map((item) => <option key={item} value={item}>{item}</option>)}</select></label>
          <label className="compact-field">备注<input value={batchReviewNote} onChange={(event) => setBatchReviewNote(event.target.value)} placeholder="批量确认说明" /></label>
          <button className="primary" onClick={batchConfirmSelected}><Save size={15} />批量确认选中</button>
          <span className="toolbar-note">“其他/未知领域”可确认到已存在分类；若选中重复事件代表，将同步确认该事件全部成员。</span>
        </section>
      )}
      <section className="classification-workbench">
        <div className="panel category-panel">
          <h2>{title}分类</h2>
          {categories.map((item) => (
            <div key={item.name} className={`metric-row clickable ${selectedCategory === item.name ? "selected-row" : ""}`} onClick={() => openCategory(item.name)}>
              <span>{item.name}</span><strong>{item.value}</strong>
            </div>
          ))}
        </div>
        <div className="panel table-panel classification-table-panel">
          <h2>{selectedCategory}数据</h2>
          <div className="table-summary">共 {page?.total ?? 0} 条，已选 {selectedIds.length} 条。</div>
          <table>
            <thead><tr><th><input type="checkbox" checked={(page?.items.length || 0) > 0 && selectedIds.length === page?.items.length} onChange={(event) => setSelectedIds(event.target.checked ? (page?.items || []).map((item) => item.work_order_id) : [])} /></th>{identifyDuplicates && <th>重复事件</th>}<th>序号</th><th>工单</th><th>标题</th><th>问题分类</th><th>风险</th><th>确认状态</th><th>已导出</th>{reviewableCategory && <th>确认分类</th>}</tr></thead>
            <tbody>
              {page?.items.map((item, index) => (
                <tr key={`${item.id}-${item.cluster_id || "single"}`} className={`clickable ${selectedItem?.id === item.id ? "selected-row" : ""}`} onClick={() => openClassificationRow(item)}>
                  <td onClick={(event) => event.stopPropagation()}><input type="checkbox" checked={selectedIds.includes(item.work_order_id)} onChange={() => toggle(item.work_order_id)} /></td>
                  {identifyDuplicates && <td><DuplicateEventButton event={item.duplicate_event} onOpen={openDuplicate} /></td>}
                  <td>{index + 1}</td>
                  <td>{item.order_no || "未填写"}</td>
                  <td>{item.title || "未填写"}</td>
                  <td>{item.problem_category || "未填写"}</td>
                  <td><Badge value={item.priority} /></td>
                  <td><Badge value={item.review_status} /></td>
                  <td>{item.exported_at ? "是" : "否"}</td>
                  {reviewableCategory && (
                    <td className="row-actions" onClick={(event) => event.stopPropagation()}>
                      <select value={rowReviewCategories[item.id] || ""} onChange={(event) => setRowReviewCategories((prev) => ({ ...prev, [item.id]: event.target.value }))}>
                        <option value="">选择分类</option>
                        {availableReviewCategories.map((category) => <option key={category} value={category}>{category}</option>)}
                      </select>
                      <button onClick={() => confirmRow(item)}><Save size={14} />确认</button>
                    </td>
                  )}
                </tr>
              ))}
            </tbody>
          </table>
          {page?.items.length === 0 && <EmptyState text="该分类下暂无数据，请先在数据导入页对选中批次运行筛查。" />}
        </div>
      </section>
      <DuplicateEventPanel cluster={duplicateCluster} selectedMember={duplicateMember} onOpenMember={openDuplicateMember} />
      <div className="classification-detail-scroll">
        <WorkOrderDetailPanel selected={selectedDetail} />
      </div>
      {selectedItem && (
        <section className="panel detail">
          <h2>人工确认</h2>
          <div className="review-form">
            <label>分类<select value={reviewCategory} onChange={(event) => setReviewCategory(event.target.value)}>{availableReviewCategories.map((item) => <option key={item} value={item}>{item}</option>)}</select></label>
            <label>备注<input value={reviewNote} onChange={(event) => setReviewNote(event.target.value)} placeholder="可填写确认依据或补充说明" /></label>
            <button className="primary" onClick={confirmSelected}><Save size={15} />确认当前分类</button>
          </div>
        </section>
      )}
      <button className="floating-action" onClick={() => openLabeling(module, modules[module as keyof typeof modules]?.view || "publicInterest")}><FileSearch size={16} />线索标注</button>
    </div>
  );
}

function Labeling({ context, setView }: { context: LabelingContext; setView: (view: View) => void }) {
  const [activeModule, setActiveModule] = useState(normalizeLabelingModule(context.module));
  const [rules, setRules] = useState<any[]>([]);
  const [selectedRule, setSelectedRule] = useState<any | null>(null);
  const [ruleMatches, setRuleMatches] = useState<Page<WorkOrder> | null>(null);
  const [hideExported, setHideExported] = useState(false);
  const [selectedIds, setSelectedIds] = useState<number[]>([]);
  const [selectedMatch, setSelectedMatch] = useState<any | null>(null);
  const [ruleMessage, setRuleMessage] = useState("");
  const [newRuleForm, setNewRuleForm] = useState<RuleFormState>(() => defaultRuleForm(activeModule));
  const [editRuleForm, setEditRuleForm] = useState<RuleFormState>(() => defaultRuleForm(activeModule));
  const [editingRuleId, setEditingRuleId] = useState<number | null>(null);

  const refreshRules = (module = activeModule) => api.rules(`?module=${module}`).then((res) => setRules(res as any[]));
  useEffect(() => {
    setActiveModule(normalizeLabelingModule(context.module));
  }, [context.module]);
  useEffect(() => {
    setNewRuleForm(defaultRuleForm(activeModule));
    setEditRuleForm(defaultRuleForm(activeModule));
    setEditingRuleId(null);
    setSelectedRule(null);
    setRuleMatches(null);
    setSelectedMatch(null);
    setSelectedIds([]);
    refreshRules(activeModule);
  }, [activeModule]);

  async function openRule(rule: any) {
    setSelectedRule(rule);
    setSelectedMatch(null);
    setSelectedIds([]);
    const res = await api.ruleMatches(rule.id, "?page_size=500") as Page<WorkOrder>;
    setRuleMatches(hideExported ? { ...res, items: res.items.filter((item) => !item.exported_at) } : res);
  }

  useEffect(() => {
    if (selectedRule) openRule(selectedRule);
  }, [hideExported]);

  async function openMatch(id: number) {
    setSelectedMatch(await api.workOrder(id));
  }

  function cancelEdit() {
    setEditingRuleId(null);
    setEditRuleForm(defaultRuleForm(activeModule));
  }

  function editRule(rule: any) {
    setEditingRuleId(rule.id);
    setEditRuleForm({ name: rule.name, module: rule.module || activeModule, domain: rule.domain, keywords: rule.keywords, weight: Number(rule.weight) || 1, enabled: !!rule.enabled });
    setRuleMessage(`正在编辑线索标注“${rule.name}”`);
  }

  async function createInlineRule() {
    setRuleMessage("");
    const saved = await api.createRule(rulePayload(newRuleForm, activeModule)) as any;
    setRuleMessage(`线索标注“${saved.name}”已新增。重新筛查后生效。`);
    setNewRuleForm(defaultRuleForm(activeModule));
    await refreshRules(activeModule);
    await openRule(saved);
  }

  async function saveEditedRule(rule: any) {
    if (!editingRuleId) return;
    setRuleMessage("");
    const saved = await api.updateRule(editingRuleId, rulePayload(editRuleForm, activeModule)) as any;
    setRuleMessage(`线索标注“${saved.name}”已更新。重新筛查后生效。`);
    cancelEdit();
    await refreshRules(activeModule);
    await openRule(saved || rule);
  }

  async function deleteRule(rule: any) {
    if (!window.confirm(`确认删除线索标注“${rule.name}”？`)) return;
    await api.deleteRule(rule.id);
    if (selectedRule?.id === rule.id) {
      setSelectedRule(null);
      setRuleMatches(null);
      setSelectedMatch(null);
    }
    if (editingRuleId === rule.id) cancelEdit();
    setRuleMessage(`线索标注“${rule.name}”已删除。`);
    await refreshRules(activeModule);
  }
  function toggle(id: number) {
    setSelectedIds((prev) => prev.includes(id) ? prev.filter((item) => item !== id) : [...prev, id]);
  }
  async function exportSelectedMatches() {
    if (selectedIds.length === 0) {
      setRuleMessage("请先勾选命中记录。");
      return;
    }
    await exportAndDownload({ export_type: activeModule, module: activeModule, work_order_ids: selectedIds });
    setRuleMessage("命中记录已导出，相关工单已标记为已导出。");
    if (selectedRule) await openRule(selectedRule);
  }

  return (
    <div className="stack workbench-page labeling-page">
      <section className="panel toolbar workbench-toolbar">
        <div className="segmented">
          {Object.entries(modules).map(([key, item]) => (
            <button key={key} className={activeModule === key ? "active" : ""} onClick={() => setActiveModule(key)}>{item.label}</button>
          ))}
        </div>
        <div className="toolbar-group toolbar-actions">
          {context.returnView && <button onClick={() => setView(context.returnView || "publicInterest")}>返回</button>}
          <label className="checkbox inline-checkbox"><input type="checkbox" checked={hideExported} onChange={(event) => setHideExported(event.target.checked)} />去除已导出</label>
          <button onClick={exportSelectedMatches}><Download size={15} />导出选中命中记录</button>
        </div>
      </section>
      {ruleMessage && <div className="notice compact-notice">{ruleMessage}</div>}
      <section className="panel table-panel labeling-rules-panel">
        <div className="detail-heading">
          <h2>{moduleLabel(activeModule)}线索标注</h2>
          <span className="table-summary">共 {rules.length} 条，点击规则查看命中记录。</span>
        </div>
        <table className="labeling-rules-table">
          <thead><tr><th>序号</th><th>标注名称</th><th>分类</th><th>关键词</th><th>权重</th><th>状态</th><th>操作</th></tr></thead>
          <tbody>
            <tr className="inline-new-row">
              <td>新增</td>
              <td><input value={newRuleForm.name} onChange={(event) => setNewRuleForm({ ...newRuleForm, name: event.target.value })} placeholder="标注名称" /></td>
              <td><input list="domain-options" value={newRuleForm.domain} onChange={(event) => setNewRuleForm({ ...newRuleForm, domain: event.target.value })} /></td>
              <td><textarea className="keyword-editor" value={newRuleForm.keywords} onChange={(event) => setNewRuleForm({ ...newRuleForm, keywords: event.target.value })} placeholder="关键词用逗号分隔" /></td>
              <td><input type="number" min="0.1" step="0.1" value={newRuleForm.weight} onChange={(event) => setNewRuleForm({ ...newRuleForm, weight: Number(event.target.value) })} /></td>
              <td><label className="checkbox inline-checkbox"><input type="checkbox" checked={newRuleForm.enabled} onChange={(event) => setNewRuleForm({ ...newRuleForm, enabled: event.target.checked })} />启用</label></td>
              <td className="row-actions"><button className="primary" onClick={createInlineRule}><Save size={14} />新增</button></td>
            </tr>
            {rules.map((rule, index) => {
              const editing = editingRuleId === rule.id;
              return (
                <tr key={rule.id} className={`clickable ${selectedRule?.id === rule.id ? "selected-row" : ""} ${editing ? "editing-row" : ""}`} onClick={() => !editing && openRule(rule)}>
                  <td>{index + 1}</td>
                  {editing ? (
                    <>
                      <td><input value={editRuleForm.name} onChange={(event) => setEditRuleForm({ ...editRuleForm, name: event.target.value })} /></td>
                      <td><input list="domain-options" value={editRuleForm.domain} onChange={(event) => setEditRuleForm({ ...editRuleForm, domain: event.target.value })} /></td>
                      <td><textarea className="keyword-editor" value={editRuleForm.keywords} onChange={(event) => setEditRuleForm({ ...editRuleForm, keywords: event.target.value })} /></td>
                      <td><input type="number" min="0.1" step="0.1" value={editRuleForm.weight} onChange={(event) => setEditRuleForm({ ...editRuleForm, weight: Number(event.target.value) })} /></td>
                      <td><label className="checkbox inline-checkbox"><input type="checkbox" checked={editRuleForm.enabled} onChange={(event) => setEditRuleForm({ ...editRuleForm, enabled: event.target.checked })} />启用</label></td>
                      <td className="row-actions">
                        <button className="primary" onClick={(event) => { event.stopPropagation(); saveEditedRule(rule); }}><Save size={14} />保存</button>
                        <button onClick={(event) => { event.stopPropagation(); cancelEdit(); }}><X size={14} />取消</button>
                      </td>
                    </>
                  ) : (
                    <>
                      <td>{rule.name}</td>
                      <td>{rule.domain}</td>
                      <td><span className="keyword-summary" title={rule.keywords}>{keywordSummary(rule.keywords)}</span></td>
                      <td>{rule.weight}</td>
                      <td><Badge value={rule.enabled ? "启用" : "停用"} /></td>
                      <td className="row-actions">
                        <button onClick={(event) => { event.stopPropagation(); editRule(rule); }}><Pencil size={14} />编辑</button>
                        <button className="danger-button" onClick={(event) => { event.stopPropagation(); deleteRule(rule); }}><Trash2 size={14} />删除</button>
                      </td>
                    </>
                  )}
                </tr>
              );
            })}
          </tbody>
        </table>
        <datalist id="domain-options">{(moduleCategories[activeModule] || []).map((item) => <option key={item} value={item} />)}</datalist>
      </section>
      <section className="labeling-results-grid">
        <section className="panel table-panel labeling-matches-panel">
          <h2>{selectedRule ? `“${selectedRule.name}”命中记录` : "命中记录"}</h2>
          <div className="table-summary">{selectedRule ? `命中 ${ruleMatches?.items.length ?? 0} 条，已选 ${selectedIds.length} 条。` : "点击上方任一规则后查看命中记录。"}</div>
          {selectedRule ? (
            <table>
              <thead><tr><th><input type="checkbox" checked={(ruleMatches?.items.length || 0) > 0 && selectedIds.length === ruleMatches?.items.length} onChange={(event) => setSelectedIds(event.target.checked ? (ruleMatches?.items || []).map((item) => item.id) : [])} /></th><th>序号</th><th>编号</th><th>标题</th><th>问题分类</th><th>街乡镇</th><th>命中关键词</th><th>已导出</th></tr></thead>
              <tbody>
                {ruleMatches?.items.map((item: any, index) => (
                  <tr key={item.id} className={`clickable ${selectedMatch?.id === item.id ? "selected-row" : ""}`} onClick={() => openMatch(item.id)}>
                    <td onClick={(event) => event.stopPropagation()}><input type="checkbox" checked={selectedIds.includes(item.id)} onChange={() => toggle(item.id)} /></td>
                    <td>{index + 1}</td><td>{item.order_no}</td><td>{item.title}</td><td>{item.problem_category}</td><td>{item.town}</td><td>{(item.matched_keywords || []).join("、")}</td><td>{item.exported_at ? "是" : "否"}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          ) : <EmptyState text="请选择一条线索标注。" />}
        </section>
        <div className="labeling-detail-panel">
          {selectedMatch ? <WorkOrderDetailPanel selected={selectedMatch} /> : <section className="panel detail placeholder-detail"><h2>工单详情</h2><EmptyState text="点击命中记录后在这里查看完整工单信息。" /></section>}
        </div>
      </section>
    </div>
  );
}

function Alerts() {
  const [page, setPage] = useState<Page<Classification> | null>(null);
  const [selected, setSelected] = useState<any | null>(null);
  const [selectedIds, setSelectedIds] = useState<number[]>([]);
  const [message, setMessage] = useState("");
  const load = () => api.classifications("?page_size=120&priority=高&module=&dedupe_work_orders=true").then((res) => setPage(res as Page<Classification>));
  useEffect(() => { load(); }, []);
  function toggle(id: number) {
    setSelectedIds((prev) => prev.includes(id) ? prev.filter((item) => item !== id) : [...prev, id]);
  }
  async function exportSelectedAlerts() {
    if (selectedIds.length === 0) {
      setMessage("请先勾选要导出的预警数据。");
      return;
    }
    await exportAndDownload({ export_type: "alerts_selected", work_order_ids: selectedIds });
    setMessage("预警数据已导出，相关工单已标记为已导出。");
    setSelectedIds([]);
    await load();
  }
  return (
    <div className="stack">
      {message && <div className="notice">{message}</div>}
      <section className="panel toolbar">
        <button className="primary" onClick={exportSelectedAlerts}><Download size={15} />导出选中预警</button>
        <span>已选 {selectedIds.length} 条。</span>
      </section>
      <section className="panel table-panel">
        <h2>高风险预警</h2>
        <table>
          <thead><tr><th><input type="checkbox" checked={(page?.items.length || 0) > 0 && selectedIds.length === page?.items.length} onChange={(event) => setSelectedIds(event.target.checked ? (page?.items || []).map((item) => item.work_order_id) : [])} /></th><th>序号</th><th>工单</th><th>标题</th><th>板块</th><th>成案领域/分类</th><th>风险</th><th>确认状态</th><th>是否解决</th><th>满意度</th><th>点位</th></tr></thead>
          <tbody>
            {page?.items.map((item, index) => (
              <tr key={item.id} className={`clickable ${selected?.id === item.work_order_id ? "selected-row" : ""}`} onClick={async () => setSelected(await api.workOrder(item.work_order_id))}>
                <td onClick={(event) => event.stopPropagation()}><input type="checkbox" checked={selectedIds.includes(item.work_order_id)} onChange={() => toggle(item.work_order_id)} /></td>
                <td>{index + 1}</td><td>{item.order_no}</td><td>{item.title}</td><td>{moduleLabel(item.module)}</td><td>{item.category}</td><td><Badge value={item.priority} /></td><td><Badge value={item.review_status} /></td><td><Badge value={item.is_resolved} /></td><td><Badge value={item.satisfaction} /></td><td>{item.location_point}</td>
              </tr>
            ))}
          </tbody>
        </table>
        {page?.items.length === 0 && <EmptyState text="暂无高风险预警。请在数据导入页运行筛查。" />}
      </section>
      <WorkOrderDetailPanel selected={selected} />
    </div>
  );
}

function Clusters() {
  const [page, setPage] = useState<Page<Cluster> | null>(null);
  const [selected, setSelected] = useState<any | null>(null);
  const [selectedMember, setSelectedMember] = useState<any | null>(null);
  const [selectedClusterIds, setSelectedClusterIds] = useState<number[]>([]);
  const [message, setMessage] = useState("");
  const load = () => api.clusters("?page_size=50").then((res) => setPage(res as Page<Cluster>));
  useEffect(() => { load(); }, []);
  async function openCluster(cluster: Cluster) {
    setSelectedMember(null);
    setSelected(await api.clusterDetail(cluster.id));
  }
  function toggle(id: number) {
    setSelectedClusterIds((prev) => prev.includes(id) ? prev.filter((item) => item !== id) : [...prev, id]);
  }
  async function exportSelectedClusters() {
    if (selectedClusterIds.length === 0) {
      setMessage("请先勾选要导出的屡诉未决事件。");
      return;
    }
    await exportAndDownload({ export_type: "clusters_selected", cluster_ids: selectedClusterIds });
    setMessage("屡诉未决事件已导出，事件成员工单已标记为已导出。");
    setSelectedClusterIds([]);
    await load();
  }
  return (
    <div className="stack">
      {message && <div className="notice">{message}</div>}
      <section className="panel toolbar">
        <button className="primary" onClick={exportSelectedClusters}><Download size={15} />导出选中事件</button>
        <span>已选 {selectedClusterIds.length} 个屡诉未决事件。</span>
      </section>
      <section className="panel table-panel">
        <h2>屡诉未决事件簇</h2>
        <table>
          <thead><tr><th><input type="checkbox" checked={(page?.items.length || 0) > 0 && selectedClusterIds.length === page?.items.length} onChange={(event) => setSelectedClusterIds(event.target.checked ? (page?.items || []).map((item) => item.id) : [])} /></th><th>序号</th><th>事件</th><th>点位</th><th>次数</th><th>未解决</th><th>不满意</th><th>风险</th></tr></thead>
          <tbody>
            {page?.items.map((item, index) => (
              <tr key={item.id} className={`clickable ${selected?.id === item.id ? "selected-row" : ""}`} onClick={() => openCluster(item)}>
                <td onClick={(event) => event.stopPropagation()}><input type="checkbox" checked={selectedClusterIds.includes(item.id)} onChange={() => toggle(item.id)} /></td>
                <td>{index + 1}</td><td>{item.title}</td><td>{item.location_point}</td><td>{item.complaint_count}</td><td>{item.unresolved_count}</td><td>{item.dissatisfied_count}</td><td><Badge value={item.risk_level} /></td>
              </tr>
            ))}
          </tbody>
        </table>
        {page?.items.length === 0 && <EmptyState text="暂无屡诉未决事件。导入数据后运行筛查会同步聚合。" />}
      </section>
      {selected && (
        <section className="panel detail">
          <h2>{selected.title}</h2>
          <div className="detail-grid">
            <DetailField label="事件ID" value={selected.id} />
            <DetailField label="街乡镇" value={selected.town} />
            <DetailField label="点位" value={selected.location_point} />
            <DetailField label="风险等级" value={selected.risk_level} />
            <DetailField label="投诉次数" value={selected.complaint_count} />
            <DetailField label="未解决" value={selected.unresolved_count} />
            <DetailField label="不满意" value={selected.dissatisfied_count} />
            <DetailField label="代表工单" value={selected.representative_order?.order_no || selected.representative_order_id} />
          </div>
          <h3>识别理由</h3>
          <p>{selected.match_reason || "同一具体对象，问题分类和标题/内容高度相近。"}</p>
          {selected.representative_order && (
            <>
              <h3>代表事件</h3>
              <div className="representative-card clickable" onClick={() => setSelectedMember(selected.representative_order)}>
                <strong>{selected.representative_order.order_no || "未填写编号"}</strong>
                <span>{selected.representative_order.title || "未填写标题"}</span>
              </div>
            </>
          )}
          <h3>成员工单</h3>
          <div className="table-panel embedded-table">
            <table>
              <thead><tr><th>序号</th><th>编号</th><th>标题</th><th>分类</th><th>解决</th><th>满意度</th><th>点位</th></tr></thead>
              <tbody>
                {(selected.members || []).map((item: WorkOrder, index: number) => (
                  <tr key={item.id} className={`clickable ${selectedMember?.id === item.id ? "selected-row" : ""}`} onClick={async () => setSelectedMember(await api.workOrder(item.id))}>
                    <td>{index + 1}</td><td>{item.order_no}</td><td>{item.title}</td><td>{item.problem_category}</td><td><Badge value={item.is_resolved} /></td><td><Badge value={item.satisfaction} /></td><td>{item.location_point}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </section>
      )}
      <WorkOrderDetailPanel selected={selectedMember} />
    </div>
  );
}

function LitigationPendingPanel() {
  const [page, setPage] = useState<Page<Cluster> | null>(null);
  const [selectedCluster, setSelectedCluster] = useState<any | null>(null);
  const [selectedMember, setSelectedMember] = useState<any | null>(null);
  const [selectedClusterIds, setSelectedClusterIds] = useState<number[]>([]);
  const [message, setMessage] = useState("");
  const load = () => api.clusters("?page_size=100").then((res) => setPage(res as Page<Cluster>));
  useEffect(() => { load(); }, []);

  function toggle(id: number) {
    setSelectedClusterIds((prev) => prev.includes(id) ? prev.filter((item) => item !== id) : [...prev, id]);
  }

  async function openCluster(cluster: Cluster) {
    setSelectedMember(null);
    setSelectedCluster(await api.clusterDetail(cluster.id));
  }

  async function exportSelectedClusters() {
    if (selectedClusterIds.length === 0) {
      setMessage("请先勾选要导出的屡诉未决事件。");
      return;
    }
    await exportAndDownload({ export_type: "clusters_selected", cluster_ids: selectedClusterIds });
    setMessage("选中屡诉未决事件已导出，每个事件下全部重复诉求均已包含。");
    setSelectedClusterIds([]);
    await load();
  }

  return (
    <div className="stack">
      {message && <div className="notice">{message}</div>}
      <section className="panel toolbar">
        <button className="primary" onClick={exportSelectedClusters}><Download size={15} />导出选中屡诉未决</button>
        <span>已选 {selectedClusterIds.length} 个代表事件。导出时会包含所选事件下全部重复诉求。</span>
      </section>
      <section className="panel table-panel">
        <h2>屡诉未决事件</h2>
        <table>
          <thead><tr><th><input type="checkbox" checked={(page?.items.length || 0) > 0 && selectedClusterIds.length === page?.items.length} onChange={(event) => setSelectedClusterIds(event.target.checked ? (page?.items || []).map((item) => item.id) : [])} /></th><th>序号</th><th>代表事件</th><th>点位</th><th>次数</th><th>持续天数</th><th>未解决</th><th>不满意</th><th>严重程度</th><th>介入建议</th></tr></thead>
          <tbody>
            {page?.items.map((item, index) => (
              <tr key={item.id} className={`clickable ${selectedCluster?.id === item.id ? "selected-row" : ""}`} onClick={() => openCluster(item)}>
                <td onClick={(event) => event.stopPropagation()}><input type="checkbox" checked={selectedClusterIds.includes(item.id)} onChange={() => toggle(item.id)} /></td>
                <td>{index + 1}</td><td>{item.title}</td><td>{item.location_point}</td><td>{item.complaint_count}</td><td>{item.duration_days ?? 0}</td><td>{item.unresolved_count}</td><td>{item.dissatisfied_count}</td><td><Badge value={item.severity_level || item.risk_level} /></td><td>{item.intervention_advice || "暂不建议"}</td>
              </tr>
            ))}
          </tbody>
        </table>
        {page?.items.length === 0 && <EmptyState text="暂无屡诉未决事件。导入数据后运行筛查会同步聚合。" />}
      </section>
      <DuplicateEventPanel cluster={selectedCluster} selectedMember={selectedMember} onOpenMember={async (id) => setSelectedMember(await api.workOrder(id))} />
      <WorkOrderDetailPanel selected={selectedMember} />
    </div>
  );
}

function AlertCenterPanel() {
  const [page, setPage] = useState<Page<Classification> | null>(null);
  const [selected, setSelected] = useState<any | null>(null);
  const [selectedIds, setSelectedIds] = useState<number[]>([]);
  const [identifyDuplicates, setIdentifyDuplicates] = useState(false);
  const [duplicateCluster, setDuplicateCluster] = useState<any | null>(null);
  const [duplicateMember, setDuplicateMember] = useState<any | null>(null);
  const [message, setMessage] = useState("");
  const load = () => {
    const params = new URLSearchParams({ page_size: "120", priority: "高", module: "", dedupe_work_orders: "true" });
    if (identifyDuplicates) params.set("identify_duplicates", "true");
    return api.classifications(`?${params.toString()}`).then((res) => {
      setPage(res as Page<Classification>);
      setSelectedIds([]);
      setSelected(null);
      setDuplicateCluster(null);
      setDuplicateMember(null);
    });
  };
  useEffect(() => { load(); }, [identifyDuplicates]);

  function toggle(id: number) {
    setSelectedIds((prev) => prev.includes(id) ? prev.filter((item) => item !== id) : [...prev, id]);
  }

  async function openDuplicate(event: DuplicateEvent) {
    setSelected(null);
    setDuplicateMember(null);
    setDuplicateCluster(await api.clusterDetail(event.cluster_id));
  }

  async function openAlertRow(item: Classification) {
    if (identifyDuplicates && item.is_duplicate_representative && item.duplicate_event) {
      await openDuplicate(item.duplicate_event);
      return;
    }
    setDuplicateCluster(null);
    setDuplicateMember(null);
    setSelected(await api.workOrder(item.work_order_id));
  }

  async function exportSelectedAlerts() {
    if (selectedIds.length === 0) {
      setMessage("请先勾选要导出的预警数据。");
      return;
    }
    const rows = (page?.items || []).filter((item) => selectedIds.includes(item.work_order_id));
    await exportAndDownload(duplicateAwareExportBody({ export_type: "alerts_selected", identify_duplicates: identifyDuplicates }, rows));
    setMessage(identifyDuplicates ? "预警数据已导出：选中重复事件的全部投诉已包含，相关工单已标记为已导出。" : "预警数据已导出，相关工单已标记为已导出。");
    setSelectedIds([]);
    await load();
  }

  return (
    <div className="stack">
      {message && <div className="notice">{message}</div>}
      <section className="panel toolbar">
        <label className="checkbox inline-checkbox"><input type="checkbox" checked={identifyDuplicates} onChange={(event) => setIdentifyDuplicates(event.target.checked)} />识别重复事件</label>
        <button className="primary" onClick={exportSelectedAlerts}><Download size={15} />导出选中预警</button>
        <span>已选 {selectedIds.length} 条。预警中心按高风险筛查分类结果展示，公益类会显示具体成案领域。</span>
        {identifyDuplicates && <span className="toolbar-note">开启后，同一重复事件只显示代表数据；点击代表数据可查看全部投诉，导出选中时包含该事件全部成员。</span>}
      </section>
      <section className="panel table-panel">
        <h2>预警中心</h2>
        <table>
          <thead><tr><th><input type="checkbox" checked={(page?.items.length || 0) > 0 && selectedIds.length === page?.items.length} onChange={(event) => setSelectedIds(event.target.checked ? (page?.items || []).map((item) => item.work_order_id) : [])} /></th>{identifyDuplicates && <th>重复事件</th>}<th>序号</th><th>工单</th><th>标题</th><th>板块</th><th>成案领域/分类</th><th>风险</th><th>确认状态</th><th>是否解决</th><th>满意度</th><th>点位</th></tr></thead>
          <tbody>
            {page?.items.map((item, index) => (
              <tr key={`${item.id}-${item.cluster_id || "single"}`} className={`clickable ${selected?.id === item.work_order_id ? "selected-row" : ""}`} onClick={() => openAlertRow(item)}>
                <td onClick={(event) => event.stopPropagation()}><input type="checkbox" checked={selectedIds.includes(item.work_order_id)} onChange={() => toggle(item.work_order_id)} /></td>
                {identifyDuplicates && <td><DuplicateEventButton event={item.duplicate_event} onOpen={openDuplicate} /></td>}
                <td>{index + 1}</td><td>{item.order_no}</td><td>{item.title}</td><td>{moduleLabel(item.module)}</td><td>{item.category}</td><td><Badge value={item.priority} /></td><td><Badge value={item.review_status} /></td><td><Badge value={item.is_resolved} /></td><td><Badge value={item.satisfaction} /></td><td>{item.location_point}</td>
              </tr>
            ))}
          </tbody>
        </table>
        {page?.items.length === 0 && <EmptyState text="暂无高风险预警。请在数据导入页运行筛查。" />}
      </section>
      <DuplicateEventPanel cluster={duplicateCluster} selectedMember={duplicateMember} onOpenMember={async (id) => setDuplicateMember(await api.workOrder(id))} />
      <WorkOrderDetailPanel selected={selected || duplicateMember} />
    </div>
  );
}

function PerformanceTrendPanel() {
  const [performanceRows, setPerformanceRows] = useState<PerformanceAnomaly[]>([]);
  const [performanceDimension, setPerformanceDimension] = useState("host_unit");
  const [performancePeriod, setPerformancePeriod] = useState("month");
  const [trendRows, setTrendRows] = useState<TrendItem[]>([]);
  const [trendPeriod, setTrendPeriod] = useState("month");
  const [trendGroup, setTrendGroup] = useState("category");
  const [selectedCluster, setSelectedCluster] = useState<any | null>(null);
  const [selectedMember, setSelectedMember] = useState<any | null>(null);

  async function loadPerformance() {
    const params = new URLSearchParams({ dimension: performanceDimension, period: performancePeriod });
    setPerformanceRows(await api.performanceAnomalies(`?${params.toString()}`) as PerformanceAnomaly[]);
  }
  async function loadTrends() {
    const params = new URLSearchParams({ period: trendPeriod, group_by: trendGroup });
    setTrendRows(await api.trends(`?${params.toString()}`) as TrendItem[]);
  }
  useEffect(() => { loadPerformance(); }, [performanceDimension, performancePeriod]);
  useEffect(() => { loadTrends(); }, [trendPeriod, trendGroup]);

  async function openAssessment(row: PerformanceAnomaly) {
    if (!row.cluster_id) return;
    setSelectedMember(null);
    setSelectedCluster(await api.clusterDetail(row.cluster_id));
  }

  return (
    <div className="stack">
      <section className="panel toolbar">
        <label className="compact-field">履职维度<select value={performanceDimension} onChange={(event) => setPerformanceDimension(event.target.value)}><option value="host_unit">主办单位</option><option value="town">街乡镇</option><option value="category">公益成案领域</option></select></label>
        <label className="compact-field">履职周期<select value={performancePeriod} onChange={(event) => setPerformancePeriod(event.target.value)}><option value="week">周度</option><option value="month">月度</option><option value="quarter">季度</option></select></label>
        <button onClick={loadPerformance}>重新评估</button>
        <span className="toolbar-note">履职异常以“长期存在、多次反映、仍未解决”为核心评估是否建议检察公益诉讼介入。</span>
      </section>
      <section className="panel table-panel">
        <h2>履职异常严重程度评估</h2>
        <table>
          <thead><tr><th>序号</th><th>对象</th><th>工单数</th><th>解决率</th><th>满意率</th><th>响应率</th><th>未解决</th><th>不满意</th><th>严重程度</th><th>介入建议</th><th>评估理由</th></tr></thead>
          <tbody>
            {performanceRows.map((item, index) => (
              <tr key={`${item.name}-${index}`} className={item.cluster_id ? "clickable" : ""} onClick={() => openAssessment(item)}>
                <td>{index + 1}</td><td>{item.name}</td><td>{item.total}</td><td>{item.solve_rate}%</td><td>{item.satisfaction_rate}%</td><td>{item.response_rate}%</td><td>{item.unresolved}</td><td>{item.dissatisfied}</td><td><Badge value={item.severity_level || "一般"} /></td><td>{item.intervention_advice || "暂不建议"}</td><td>{item.assessment_reason || item.anomaly || "未触发"}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </section>
      <DuplicateEventPanel cluster={selectedCluster} selectedMember={selectedMember} onOpenMember={async (id) => setSelectedMember(await api.workOrder(id))} />
      <WorkOrderDetailPanel selected={selectedMember} />
      <section className="panel toolbar">
        <label className="compact-field">趋势粒度<select value={trendPeriod} onChange={(event) => setTrendPeriod(event.target.value)}><option value="week">周度</option><option value="month">月度</option><option value="quarter">季度</option></select></label>
        <label className="compact-field">统计对象<select value={trendGroup} onChange={(event) => setTrendGroup(event.target.value)}><option value="category">公益成案领域</option><option value="problem_category">问题分类</option><option value="town">街乡镇</option></select></label>
        <button onClick={loadTrends}>重新分析</button>
      </section>
      <section className="panel table-panel">
        <h2>投诉趋势分析</h2>
        <table><thead><tr><th>序号</th><th>问题</th><th>最新周期</th><th>数量</th><th>上一周期</th><th>数量</th><th>变化率</th><th>标签</th></tr></thead><tbody>{trendRows.map((item, index) => <tr key={`${item.name}-${index}`}><td>{index + 1}</td><td>{item.name}</td><td>{item.latest_period}</td><td>{item.latest_count}</td><td>{item.previous_period}</td><td>{item.previous_count}</td><td>{item.change_rate}%</td><td><Badge value={item.tag} /></td></tr>)}</tbody></table>
      </section>
    </div>
  );
}

function AdvancedAnalysis() {
  const [tab, setTab] = useState<"clusters" | "alerts" | "performance">("clusters");
  const tabs = [
    ["clusters", "屡诉未决"],
    ["alerts", "预警中心"],
    ["performance", "履职异常与趋势"],
  ] as const;

  return (
    <div className="stack">
      <section className="panel toolbar">
        <div className="segmented">
          {tabs.map(([key, label]) => <button key={key} className={tab === key ? "active" : ""} onClick={() => setTab(key)}>{label}</button>)}
        </div>
      </section>
      {tab === "clusters" && <LitigationPendingPanel />}
      {tab === "alerts" && <AlertCenterPanel />}
      {tab === "performance" && <PerformanceTrendPanel />}
    </div>
  );
}

function Admin() {
  const [audits, setAudits] = useState<any[]>([]);
  const [config, setConfig] = useState<any>({});
  const [message, setMessage] = useState("");
  const [selectedAudit, setSelectedAudit] = useState<Record<string, unknown> | null>(null);
  useEffect(() => {
    api.auditLogs().then((res) => setAudits(res as any[])).catch(() => setAudits([]));
    api.llmConfig().then((res) => setConfig(res as any)).catch(() => setConfig({}));
  }, []);
  async function save() {
    await api.saveLlmConfig(config);
    setMessage("配置已保存。启用外部模型后将按当前要求发送原始工单内容。");
  }
  return (
    <div className="stack">
      <section className="panel table-panel">
        <h2>大模型配置</h2>
        <div className="form-grid">
          <label>供应商<input value={config.provider || ""} onChange={(e) => setConfig({ ...config, provider: e.target.value })} /></label>
          <label>Base URL<input value={config.base_url || ""} onChange={(e) => setConfig({ ...config, base_url: e.target.value })} /></label>
          <label>模型<input value={config.model || ""} onChange={(e) => setConfig({ ...config, model: e.target.value })} /></label>
          <label>API Key<input type="password" onChange={(e) => setConfig({ ...config, api_key: e.target.value })} placeholder={config.api_key_masked || "未配置"} /></label>
        </div>
        <label className="checkbox"><input type="checkbox" checked={!!config.enabled} onChange={(e) => setConfig({ ...config, enabled: e.target.checked })} />启用外部模型增强</label>
        <button className="primary" onClick={save}><Settings size={16} />保存配置</button>
        {message && <div className="notice">{message}</div>}
      </section>
      <section className="panel table-panel">
        <h2>审计日志</h2>
        <table>
          <thead><tr><th>序号</th><th>用户</th><th>动作</th><th>对象</th><th>说明</th><th>时间</th></tr></thead>
          <tbody>
            {audits.map((item, index) => (
              <tr key={item.id} className={`clickable ${selectedAudit?.id === item.id ? "selected-row" : ""}`} onClick={() => setSelectedAudit(item as Record<string, unknown>)}>
                <td>{index + 1}</td><td>{item.username}</td><td>{item.action}</td><td>{item.target_type}</td><td>{item.detail}</td><td>{new Date(item.created_at).toLocaleString()}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </section>
      <RecordDetailPanel title="审计日志完整信息" record={selectedAudit} />
    </div>
  );
}

export function App() {
  const [session, setCurrentSession] = useState<Session | null>(() => getSession());
  const [view, setView] = useState<View>("imports");
  const [workOrderFilter, setWorkOrderFilter] = useState<WorkOrderFilter>({ title: "全部工单", refreshKey: 0 });
  const [labelingContext, setLabelingContext] = useState<LabelingContext>({ module: "public_interest" });
  const [importState, setImportState] = useState<ImportState>({
    message: "上传 Excel 后可勾选一个或多个导入批次，在本页直接运行公益成案领域、弱势群体、行政违法筛查。",
    busy: false,
    refreshKey: 0,
    lastSuccess: false
  });

  useEffect(() => {
    const handleExpired = () => setCurrentSession(null);
    window.addEventListener("qc-auth-expired", handleExpired);
    return () => window.removeEventListener("qc-auth-expired", handleExpired);
  }, []);

  function openWorkOrders(filter: Omit<WorkOrderFilter, "refreshKey">) {
    setWorkOrderFilter({ ...filter, refreshKey: Date.now() });
    setView("orders");
  }

  function openLabeling(module: string, returnView?: View) {
    setLabelingContext({ module, returnView });
    setView("labeling");
  }

  const content = useMemo(() => {
    if (!session) return null;
    switch (view) {
      case "imports":
        return <Imports importState={importState} setImportState={setImportState} session={session} />;
      case "orders":
        return <WorkOrders filter={workOrderFilter} />;
      case "publicInterest":
        return <ClassificationPage module="public_interest" title="公益成案领域" openLabeling={openLabeling} />;
      case "vulnerable":
        return <ClassificationPage module="vulnerable" title="弱势群体" openLabeling={openLabeling} />;
      case "administrative":
        return <ClassificationPage module="administrative" title="行政违法" openLabeling={openLabeling} />;
      case "labeling":
        return <Labeling context={labelingContext} setView={setView} />;
      case "analysis":
        return <AdvancedAnalysis />;
      case "admin":
        return <Admin />;
      default:
        return <Dashboard openWorkOrders={openWorkOrders} openAnalysis={() => setView("analysis")} />;
    }
  }, [view, importState, workOrderFilter, session, labelingContext]);

  if (!session) return <Login onLogin={setCurrentSession} />;
  return (
    <Layout session={session} view={view} setView={setView} onLogout={() => { setSession(null); setCurrentSession(null); }}>
      {content}
    </Layout>
  );
}
