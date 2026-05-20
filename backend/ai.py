from __future__ import annotations

import json
import os
import re
import urllib.error
import urllib.request
from datetime import date
from typing import Any


NARRATOR_LABELS = {
    "male": "男方",
    "female": "女方",
    "both": "双方",
    "unknown": "未知",
}


def analyze_event(event: dict[str, Any], context: list[str]) -> dict[str, Any]:
    prompt = build_analysis_prompt(event, context)
    ollama_result = call_ollama_json(prompt)
    if ollama_result is not None:
        return normalize_analysis(ollama_result, provider="ollama")
    return rule_based_analysis(event, context)


def enrich_from_text(content: str, context: list[str]) -> dict[str, Any]:
    prompt = build_enrich_prompt(content, context)
    ollama_result = call_ollama_json(prompt)
    if ollama_result is not None:
        return normalize_enrichment(ollama_result)
    return rule_based_enrichment(content)


def build_enrich_prompt(content: str, context: list[str]) -> str:
    context_text = "\n".join(f"- {item}" for item in context[-6:]) or "- 无"
    return f"""
你是关系事件结构化助手。请从输入文本中提取结构化字段。
只输出 JSON，不要 markdown，不要解释。

历史摘要：
{context_text}

输入文本：
{content}

输出字段：
{{
  "title": "简短标题，8-20字",
  "occurred_on": "YYYY-MM-DD，无法判断时用今天",
  "narrator": "male/female/both/unknown",
  "amount": "数字，无法判断填0",
  "currency": "CNY/USD 等，默认 CNY",
  "emotion_score": "0-5整数",
  "tags": ["最多8个标签"],
  "relation_keywords": ["用于关联历史事件的关键词，最多6个"]
}}
""".strip()


def build_analysis_prompt(event: dict[str, Any], context: list[str]) -> str:
    context_text = "\n".join(f"- {item}" for item in context) or "- 暂无历史上下文"
    return f"""
你是一个谨慎、公正的关系事件分析助手。只基于输入文本判断，不假设未出现的事实。
只输出 JSON，不要 markdown，不要解释。

历史记忆：
{context_text}

新事件：
- 日期：{event['occurred_on']}
- 叙述者：{event['narrator_label']}
- 标题：{event['title']}
- 金额：{event['amount']:.2f} {event['currency']}
- 情绪强度：{event['emotion_score']}/5
- 标签：{', '.join(event.get('tags', [])) or '无'}
- 正文：{event['content']}

输出字段：
{{
  "core_issue": "一句话概括核心矛盾",
  "facts": ["可确认事实"],
  "claims": ["主观判断或待验证说法"],
  "needs": ["双方可能的真实需求"],
  "risk_flags": ["潜在风险，没有则空数组"],
  "suggested_questions": ["为了更客观还应追问的问题"],
  "fairness_score": "0到100整数，50表示无法判断，越高表示叙述者更占理",
  "narrator_bias_note": "叙述者视角可能的偏差",
  "next_action": "一条具体、温和、可执行建议"
}}
""".strip()


def call_ollama_json(prompt: str) -> dict[str, Any] | None:
    base_url = os.environ.get("OLLAMA_BASE_URL", "http://127.0.0.1:11434").rstrip("/")
    model = os.environ.get("OLLAMA_MODEL", "deepseek-r1")
    payload = {
        "model": model,
        "stream": False,
        "messages": [
            {"role": "system", "content": "你只输出合法 JSON。"},
            {"role": "user", "content": prompt},
        ],
        "options": {"temperature": 0.2},
    }
    request = urllib.request.Request(
        f"{base_url}/api/chat",
        data=json.dumps(payload).encode("utf-8"),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=45) as response:
            raw = json.loads(response.read().decode("utf-8"))
    except (OSError, urllib.error.URLError, TimeoutError, json.JSONDecodeError):
        return None
    content = raw.get("message", {}).get("content", "")
    return extract_json_object(content)


def extract_json_object(text: str) -> dict[str, Any] | None:
    cleaned = re.sub(r"<think>.*?</think>", "", text, flags=re.S).strip()
    match = re.search(r"\{.*\}", cleaned, flags=re.S)
    if not match:
        return None
    try:
        parsed = json.loads(match.group(0))
    except json.JSONDecodeError:
        return None
    return parsed if isinstance(parsed, dict) else None


def normalize_enrichment(payload: dict[str, Any] | None) -> dict[str, Any]:
    payload = payload or {}
    occurred_on = str(payload.get("occurred_on") or date.today().isoformat()).strip()
    narrator = str(payload.get("narrator") or "unknown").strip()
    if narrator not in NARRATOR_LABELS:
        narrator = "unknown"
    title = str(payload.get("title") or "").strip() or "关系事件记录"
    title = title[:40]
    try:
        amount = float(payload.get("amount", 0) or 0)
    except (TypeError, ValueError):
        amount = 0.0
    try:
        emotion_score = max(0, min(5, int(payload.get("emotion_score", 0))))
    except (TypeError, ValueError):
        emotion_score = 0
    tags = payload.get("tags", [])
    if isinstance(tags, str):
        tags = [x.strip() for x in tags.replace("，", ",").split(",") if x.strip()]
    if not isinstance(tags, list):
        tags = []
    keywords = payload.get("relation_keywords", [])
    if isinstance(keywords, str):
        keywords = [x.strip() for x in keywords.replace("，", ",").split(",") if x.strip()]
    if not isinstance(keywords, list):
        keywords = []
    return {
        "title": title,
        "occurred_on": occurred_on,
        "narrator": narrator,
        "amount": max(0.0, amount),
        "currency": str(payload.get("currency") or "CNY").upper()[:8],
        "emotion_score": emotion_score,
        "tags": [str(x).strip() for x in tags if str(x).strip()][:8],
        "relation_keywords": [str(x).strip() for x in keywords if str(x).strip()][:6],
        "enrichment_provider": "ollama",
    }


def rule_based_enrichment(content: str) -> dict[str, Any]:
    title = content.split("\n", 1)[0].strip()[:30] or "关系事件记录"
    amount = 0.0
    amount_match = re.search(r"(\d+(?:\.\d{1,2})?)\s*(元|块|rmb|cny)?", content.lower())
    if amount_match:
        try:
            amount = float(amount_match.group(1))
        except ValueError:
            amount = 0.0
    emotion_score = 2
    if any(w in content for w in ["吵", "崩溃", "很生气", "拉黑", "冷战"]):
        emotion_score = 4
    tags = []
    for t in ["金钱", "承诺", "沟通", "冷战", "边界", "信任"]:
        if t in content:
            tags.append(t)
    return {
        "title": title,
        "occurred_on": date.today().isoformat(),
        "narrator": "unknown",
        "amount": amount,
        "currency": "CNY",
        "emotion_score": emotion_score,
        "tags": tags[:8],
        "relation_keywords": tags[:4],
        "enrichment_provider": "local-rules",
    }


def normalize_analysis(payload: dict[str, Any] | None, provider: str) -> dict[str, Any]:
    fallback = {
        "core_issue": "信息不足，暂时只能做初步整理",
        "facts": [],
        "claims": [],
        "needs": [],
        "risk_flags": [],
        "suggested_questions": [],
        "fairness_score": 50,
        "narrator_bias_note": "当前只有单方叙述，结论需要另一方补充。",
        "next_action": "先补充对方视角和可验证事实，再讨论责任分配。",
    }
    result = {**fallback, **(payload or {})}
    for key in ["facts", "claims", "needs", "risk_flags", "suggested_questions"]:
        if isinstance(result.get(key), str):
            result[key] = [result[key]]
        elif not isinstance(result.get(key), list):
            result[key] = []
    try:
        result["fairness_score"] = max(0, min(100, int(result.get("fairness_score", 50))))
    except (TypeError, ValueError):
        result["fairness_score"] = 50
    result["provider"] = provider
    return result


def rule_based_analysis(event: dict[str, Any], context: list[str]) -> dict[str, Any]:
    content = event["content"]
    amount = event.get("amount", 0)
    emotion = int(event.get("emotion_score", 0))
    score = 50 + (6 if event["narrator"] in {"male", "female"} else 0)
    risk_flags: list[str] = []
    if amount > 1000:
        risk_flags.append("涉及较大金额，建议补充付款凭证和约定。")
    if emotion >= 4:
        risk_flags.append("情绪强度较高，建议先做事实和感受拆分。")
    if any(w in content for w in ["威胁", "辱骂", "动手", "控制"]):
        risk_flags.append("出现边界风险词，需要单独核实。")
        score += 8
    facts = [
        f"{event['occurred_on']} 发生事件：{event['title']}",
        f"记录金额 {amount:.2f} {event['currency']}" if amount else "未记录明确金额",
    ]
    if context:
        facts.append(f"参考了最近 {len(context)} 条关系记忆")
    result = {
        "core_issue": "需要从单方叙述走向双方可核实事实。",
        "facts": facts,
        "claims": ["当前责任判断主要来自叙述者表达，尚未经过对方确认。"],
        "needs": ["希望被理解并得到更清晰的责任划分。"],
        "risk_flags": risk_flags,
        "suggested_questions": [
            "对方会如何描述同一件事？",
            "这件事之前是否有明确约定？",
            "金额是共同消费、赠与还是借款？",
        ],
        "fairness_score": max(0, min(100, score)),
        "narrator_bias_note": "当前只有单方文本，不能直接裁决真实对错。",
        "next_action": "补充对方版本和证据，再做责任评估。",
        "provider": "local-rules",
    }
    return normalize_analysis(result, provider="local-rules")

