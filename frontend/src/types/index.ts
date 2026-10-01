export type Session = {
  token: string;
  username: string;
  display_name: string;
  role: string;
  permissions: string[];
};

export type Page<T> = {
  total: number;
  page: number;
  page_size: number;
  items: T[];
};

export type DashboardSummary = {
  work_orders: number;
  clues: number;
  pending_reviews: number;
  high_risk: number;
  clusters: number;
  unresolved: number;
  domain_distribution: Array<{ name: string; value: number }>;
  town_distribution: Array<{ name: string; value: number }>;
  recent_audits: Array<{ id: number; username: string; action: string; detail: string; created_at: string }>;
};

export type WorkOrder = {
  id: number;
  order_no: string;
  order_type: string;
  problem_category: string;
  title: string;
  status: string;
  caller_name: string;
  caller_phone: string;
  town: string;
  received_at?: string | null;
  closed_at?: string | null;
  host_unit: string;
  location_point: string;
  case_domain: string;
  is_resolved: string;
  satisfaction: string;
  exported_at?: string | null;
  exported_by?: string;
  export_context?: string;
  content?: string;
  handling_result?: string;
  reply_content?: string;
  extra_fields?: Array<{ name: string; value: string }>;
  duplicate_event?: DuplicateEvent | null;
  is_duplicate_representative?: boolean;
  cluster_id?: number | null;
  cluster_member_count?: number;
};

export type DuplicateEvent = {
  cluster_id: number;
  title: string;
  representative_order_id: number | null;
  complaint_count: number;
  match_reason?: string;
};

export type Classification = {
  id: number;
  work_order_id: number;
  order_no: string;
  title: string;
  problem_category: string;
  town: string;
  location_point: string;
  company_name?: string;
  module: string;
  category: string;
  priority: string;
  risk_score: number;
  review_status: string;
  rule_hits: string;
  evidence: string;
  is_resolved: string;
  satisfaction: string;
  exported_at?: string | null;
  exported_by?: string;
  export_context?: string;
  duplicate_event?: DuplicateEvent | null;
  is_duplicate_representative?: boolean;
  cluster_id?: number | null;
  cluster_member_count?: number;
  context_work_order_id?: number;
};

export type Clue = Classification & {
  predicted_domain?: string;
  status?: string;
};

export type Cluster = {
  id: number;
  title: string;
  location_point: string;
  town: string;
  complaint_count: number;
  unresolved_count: number;
  dissatisfied_count: number;
  risk_level: string;
  representative_order_id?: number | null;
  match_reason?: string;
  first_seen_at: string | null;
  last_seen_at: string | null;
  duration_days?: number;
  severity_level?: string;
  intervention_advice?: string;
  assessment_reason?: string;
  public_interest_categories?: string[];
};

export type PerformanceAnomaly = {
  name: string;
  dimension: string;
  period: string;
  total: number;
  previous_total: number;
  resolved: number;
  unresolved: number;
  dissatisfied: number;
  responded: number;
  solve_rate: number;
  satisfaction_rate: number;
  response_rate: number;
  anomaly: string;
  severity_level?: string;
  intervention_advice?: string;
  assessment_reason?: string;
  representative_event?: string;
  cluster_id?: number | null;
};

export type TrendItem = {
  name: string;
  group_by: string;
  period: string;
  latest_period: string;
  latest_count: number;
  previous_period: string;
  previous_count: number;
  change_rate: number;
  tag: string;
  series: Array<{ period: string; count: number }>;
};
