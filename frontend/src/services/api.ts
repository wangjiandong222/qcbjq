import type { Session } from "../types";

const API_BASE = import.meta.env.VITE_API_BASE || "/api";

let session: Session | null = null;

export function setSession(next: Session | null) {
  session = next;
  if (next) {
    localStorage.setItem("qc_session", JSON.stringify(next));
  } else {
    localStorage.removeItem("qc_session");
  }
}

export function getSession(): Session | null {
  if (session) return session;
  const raw = localStorage.getItem("qc_session");
  if (!raw) return null;
  try {
    const parsed = JSON.parse(raw) as Session;
    if (!parsed.token || !Array.isArray(parsed.permissions)) {
      setSession(null);
      return null;
    }
    session = parsed;
  } catch {
    setSession(null);
    return null;
  }
  return session;
}

async function request<T>(path: string, init: RequestInit = {}): Promise<T> {
  const current = getSession();
  const headers = new Headers(init.headers);
  if (!(init.body instanceof FormData)) headers.set("Content-Type", "application/json");
  if (current?.token) headers.set("Authorization", `Bearer ${current.token}`);
  let res: Response;
  try {
    res = await fetch(`${API_BASE}${path}`, { ...init, headers });
  } catch (err) {
    throw new Error("无法连接后端服务，请确认 FastAPI 已启动在 http://127.0.0.1:8000");
  }
  if (!res.ok) {
    const detail = await res.json().catch(() => ({ detail: res.statusText }));
    const rawMessage = typeof detail.detail === "string" ? detail.detail : "请求失败";
    if (res.status === 404 && path.startsWith("/")) {
      throw new Error("接口未找到。若你正在访问 http://127.0.0.1:5173，请重启前端服务以加载 /api 代理配置，并确认后端已启动在 http://127.0.0.1:8000。");
    }
    if (res.status === 401) {
      setSession(null);
      window.dispatchEvent(new Event("qc-auth-expired"));
      throw new Error("登录状态已失效，请重新登录后再操作。");
    }
    if (res.status === 403) {
      if (rawMessage.includes("Permission required: import")) {
        throw new Error("当前账号没有数据导入权限，请使用具备导入权限的管理员账号登录，或让管理员授予 import 权限。");
      }
      throw new Error(`当前账号权限不足：${rawMessage}`);
    }
    throw new Error(rawMessage);
  }
  return res.json();
}

export const api = {
  login: (username: string, password: string) =>
    request<Session>("/auth/login", { method: "POST", body: JSON.stringify({ username, password }) }),
  dashboard: () => request("/dashboard/summary"),
  imports: () => request("/imports"),
  uploadImport: (file: File) => {
    const form = new FormData();
    form.append("file", file);
    return request("/imports", { method: "POST", body: form });
  },
  deleteImport: (id: number) => request(`/imports/${id}`, { method: "DELETE" }),
  workOrders: (params = "") => request(`/work-orders${params}`),
  workOrder: (id: number) => request(`/work-orders/${id}`),
  runScreening: (body: unknown = {}) => request("/screening/run", { method: "POST", body: JSON.stringify(body) }),
  classifications: (params = "") => request(`/classifications${params}`),
  classificationCategories: (params = "") => request(`/classification-categories${params}`),
  reviewClassification: (id: number, body: unknown) => request(`/classifications/${id}/review`, { method: "PATCH", body: JSON.stringify(body) }),
  batchReviewClassifications: (body: unknown) => request("/classifications/batch-review", { method: "PATCH", body: JSON.stringify(body) }),
  clues: (params = "") => request(`/clues${params}`),
  reviewClue: (id: number, body: unknown) => request(`/clues/${id}/review`, { method: "PATCH", body: JSON.stringify(body) }),
  clusters: (params = "") => request(`/clusters${params}`),
  clusterDetail: (id: number) => request(`/clusters/${id}`),
  performanceAnomalies: (params = "") => request(`/performance/anomalies${params}`),
  trends: (params = "") => request(`/trends${params}`),
  auditLogs: () => request("/audit-logs"),
  rules: (params = "") => request(`/rules${params}`),
  createRule: (body: unknown) => request("/rules", { method: "POST", body: JSON.stringify(body) }),
  updateRule: (id: number, body: unknown) => request(`/rules/${id}`, { method: "PUT", body: JSON.stringify(body) }),
  deleteRule: (id: number) => request(`/rules/${id}`, { method: "DELETE" }),
  ruleMatches: (id: number, params = "") => request(`/rules/${id}/matches${params}`),
  exports: () => request("/exports"),
  createExport: (export_type: string) => request("/exports", { method: "POST", body: JSON.stringify({ export_type }) }),
  createSelectedExport: (body: unknown) => request("/exports/selected", { method: "POST", body: JSON.stringify(body) }),
  downloadUrl: (id: number) => `${API_BASE}/exports/${id}/download`,
  downloadExport: async (id: number, filename: string) => {
    const current = getSession();
    const res = await fetch(`${API_BASE}/exports/${id}/download`, {
      headers: current?.token ? { Authorization: `Bearer ${current.token}` } : {}
    });
    if (!res.ok) throw new Error("下载失败");
    const blob = await res.blob();
    const url = URL.createObjectURL(blob);
    const link = document.createElement("a");
    link.href = url;
    link.download = filename || `export_${id}.xlsx`;
    document.body.appendChild(link);
    link.click();
    link.remove();
    URL.revokeObjectURL(url);
  },
  llmConfig: () => request("/llm-config"),
  saveLlmConfig: (body: unknown) => request("/llm-config", { method: "POST", body: JSON.stringify(body) })
};
