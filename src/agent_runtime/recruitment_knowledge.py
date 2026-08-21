from __future__ import annotations

import json
from pathlib import Path
import re
from typing import Any

from .openai_compatible_client import OpenAICompatibleChatClient


DEFAULT_RECRUITMENT_PATH = (
    Path(__file__).resolve().parents[2]
    / "data"
    / "china_recruitment_sources.json"
)


class ChinaRecruitmentKnowledgeBase:
    """Versioned official-source corpus for China campus recruitment."""

    COMPANY_ALIASES = {
        "字节跳动": ("字节跳动", "字节"),
        "华为": ("华为",),
        "腾讯": ("腾讯",),
        "腾讯音乐娱乐": ("腾讯音乐娱乐", "腾讯音乐", "tme"),
        "阿里巴巴": ("阿里巴巴", "阿里", "阿里云"),
    }

    def __init__(self, path: str | Path = DEFAULT_RECRUITMENT_PATH) -> None:
        payload = json.loads(Path(path).read_text(encoding="utf-8"))
        self.updated_at = payload["updated_at"]
        self.documents = payload["documents"]

    def search(self, query: str, k: int = 4) -> list[dict[str, Any]]:
        normalized = self._normalize(query)
        query_years = set(re.findall(r"20\d{2}", query))
        matched_companies = {
            company
            for company, aliases in self.COMPANY_ALIASES.items()
            if any(self._normalize(alias) in normalized for alias in aliases)
        }
        if "公司" in query and not matched_companies:
            return []
        ranked: list[tuple[float, dict[str, Any]]] = []
        for document in self.documents:
            if matched_companies and document["company"] not in matched_companies:
                continue
            score = 0.0
            for tag in document["tags"]:
                if self._normalize(tag) in normalized:
                    score += 2.0 if tag in {document["company"], document["batch"]} else 1.0
            if document["company"] in query:
                score += 5.0
            document_years = set(re.findall(r"20\d{2}", document["batch"] + document["content"]))
            if query_years & document_years:
                score += 3.0
            if score > 0:
                ranked.append((score, document))
        ranked.sort(
            key=lambda item: (
                item[0],
                item[1]["status"] == "current",
            ),
            reverse=True,
        )
        return [
            {
                "citation_number": index,
                "document_id": document["source_id"],
                "source_id": document["source_id"],
                "title": f"{document['company']} {document['batch']}",
                "heading": document["application_window"],
                "handbook_year": None,
                "source_type": "china_campus_recruitment",
                "source_url": document["source_url"],
                "content": document["content"],
                "status": document["status"],
                "application_window": document["application_window"],
                "graduation_window": document["graduation_window"],
                "retrieval_channels": ["verified_metadata"],
                "score": score,
                "knowledge_updated_at": self.updated_at,
            }
            for index, (score, document) in enumerate(ranked[:k], start=1)
        ]

    @staticmethod
    def _normalize(value: str) -> str:
        return re.sub(r"[^a-z0-9\u4e00-\u9fff]+", "", value.lower())


class RecruitmentQuestionAnsweringAgent:
    def __init__(
        self,
        knowledge_base: ChinaRecruitmentKnowledgeBase,
        client: OpenAICompatibleChatClient | None = None,
    ) -> None:
        self.knowledge_base = knowledge_base
        self.client = client

    def answer(self, query: str) -> dict[str, Any]:
        evidence = self.knowledge_base.search(query)
        trace = [
            {
                "tool": "search_china_recruitment_kb",
                "ok": bool(evidence),
                "count": len(evidence),
                "updated_at": self.knowledge_base.updated_at,
            }
        ]
        if not evidence:
            return {
                "message": (
                    "当前企业校招知识库还没有匹配到这家企业或招聘批次。"
                    "请补充企业名称和毕业届次，或直接查看该企业招聘官网。"
                ),
                "evidence": [],
                "trace": trace,
                "answer_source": "recruitment_no_evidence",
                "confidence": "low",
                "next_action": "ask_company_and_graduation_cohort",
            }
        if self.client is None:
            return self._extractive(evidence, trace)
        try:
            blocks = "\n\n".join(
                f"[{item['citation_number']}] {item['title']}\n"
                f"状态：{item['status']}\n投递窗口：{item['application_window']}\n"
                f"毕业范围：{item['graduation_window']}\n正文：{item['content']}"
                for item in evidence
            )
            result = self.client.chat(
                [
                    {
                        "role": "system",
                        "content": (
                            "你是CampusPilot中国校招信息助手。只能根据证据回答并用[n]引用。"
                            "必须区分当前公告与历史公告；没有明确截止日时不得自行推测。"
                            "提醒用户企业口径会变，应在投递前打开页面下方的官方来源复核。"
                            "不要在回答正文中输出网址，不要使用[n]等占位引用，不要使用表情符号。"
                        ),
                    },
                    {"role": "user", "content": f"问题：{query}\n\n证据：\n{blocks}"},
                ],
                temperature=0.0,
            )
            content = result["message"].get("content", "").strip()
            citations = [int(value) for value in re.findall(r"\[(\d+)]", content)]
            bracket_tokens = re.findall(r"\[([^\]]+)]", content)
            urls = re.findall(r"https?://[^\s)]+", content)
            if (
                not content
                or not citations
                or any(value > len(evidence) for value in citations)
                or any(not token.isdigit() for token in bracket_tokens)
                or urls
            ):
                raise ValueError("invalid grounded recruitment answer")
            trace.append({"tool": "generate_recruitment_answer", "ok": True})
            return {
                "message": content,
                "evidence": evidence,
                "trace": trace,
                "answer_source": "llm_recruitment_grounded_answer",
                "confidence": "high",
                "next_action": "review_company_career_site",
            }
        except Exception as exc:
            trace.append(
                {"tool": "generate_recruitment_answer", "ok": False, "error": type(exc).__name__}
            )
            return self._extractive(evidence, trace)

    @staticmethod
    def _extractive(evidence: list[dict[str, Any]], trace: list[dict[str, Any]]) -> dict[str, Any]:
        lines = ["根据当前收录的企业招聘公告："]
        for item in evidence[:3]:
            lines.append(
                f"- [{item['citation_number']}] {item['title']}：投递窗口为"
                f"{item['application_window']}；毕业范围为{item['graduation_window']}。"
            )
        lines.append("招聘批次会调整，投递前请打开下方企业官方页面复核。")
        return {
            "message": "\n".join(lines),
            "evidence": evidence,
            "trace": trace,
            "answer_source": "recruitment_extractive_answer",
            "confidence": "medium",
            "next_action": "review_company_career_site",
        }
