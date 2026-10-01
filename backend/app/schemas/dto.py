from __future__ import annotations

from datetime import datetime
from pydantic import BaseModel


class LoginRequest(BaseModel):
    username: str
    password: str


class LoginResponse(BaseModel):
    token: str
    username: str
    display_name: str
    role: str
    permissions: list[str]


class PageResponse(BaseModel):
    total: int
    page: int
    page_size: int
    items: list[dict]


class DashboardSummary(BaseModel):
    work_orders: int
    clues: int
    pending_reviews: int
    high_risk: int
    clusters: int
    unresolved: int
    domain_distribution: list[dict]
    town_distribution: list[dict]
    recent_audits: list[dict]


class ScreeningRunResponse(BaseModel):
    processed: int
    clues_created: int
    clusters_created: int
    updated: int = 0
    classified_work_orders: int = 0
    classifications_created: int = 0
    classifications_updated: int = 0
    modules: list[str] = []
    message: str


class ClueReviewRequest(BaseModel):
    status: str | None = None
    review_status: str | None = None
    predicted_domain: str | None = None
    priority: str | None = None
    note: str = ""
    apply_to_cluster: bool = False


class ClassificationBatchReviewRequest(BaseModel):
    classification_ids: list[int] = []
    category: str
    note: str = ""
    apply_to_cluster: bool = False


class ExportRequest(BaseModel):
    export_type: str


class SelectedExportRequest(BaseModel):
    export_type: str
    work_order_ids: list[int] = []
    cluster_ids: list[int] = []
    representative_work_order_ids: list[int] = []
    duplicate_export_scope: str = "representative"
    module: str | None = None
    category: str | None = None
    identify_duplicates: bool = False
    hide_exported: bool = False


class ScreeningRunRequest(BaseModel):
    batch_ids: list[int] = []
    modules: list[str] = []


class LLMConfigRequest(BaseModel):
    provider: str = "openai-compatible"
    base_url: str = ""
    model: str = ""
    api_key: str = ""
    enabled: bool = False


class RuleCreateRequest(BaseModel):
    name: str
    domain: str
    keywords: str
    weight: float = 1.0
    enabled: bool = True
    module: str = "public_interest"


class RuleUpdateRequest(RuleCreateRequest):
    pass


class ImportBatchOut(BaseModel):
    id: int
    filename: str
    status: str
    total_rows: int
    success_rows: int
    failed_rows: int
    error_message: str
    imported_by: str
    created_at: datetime

    model_config = {"from_attributes": True}
