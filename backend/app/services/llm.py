from __future__ import annotations

import httpx

from app.core.config import settings


class LLMAdapter:
    """OpenAI-compatible adapter. It is deliberately optional for private deployment."""

    def __init__(self) -> None:
        self.enabled = bool(settings.llm_enabled and settings.llm_base_url and settings.llm_api_key and settings.llm_model)

    async def classify(self, work_order: dict) -> dict | None:
        if not self.enabled:
            return None
        prompt = (
            "你是检察机关12345涉检线索筛查助手。请基于原始工单判断成案领域、风险等级、理由。"
            "只返回JSON，字段为 predicted_domain, priority, evidence。"
        )
        body = {
            "model": settings.llm_model,
            "messages": [
                {"role": "system", "content": prompt},
                {"role": "user", "content": str(work_order)},
            ],
            "temperature": 0.1,
        }
        async with httpx.AsyncClient(timeout=20) as client:
            response = await client.post(
                settings.llm_base_url.rstrip("/") + "/chat/completions",
                headers={"Authorization": f"Bearer {settings.llm_api_key}"},
                json=body,
            )
            response.raise_for_status()
            content = response.json()["choices"][0]["message"]["content"]
            return {"raw": content, "payload": work_order}
