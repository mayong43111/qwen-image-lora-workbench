from __future__ import annotations

import base64
import json
import re
import urllib.error
import urllib.request
from typing import Any, Callable

from ..core.config import ANNOTATION_SETTINGS_PATH, DATASETS_PATH, DEFAULT_ANNOTATION_SETTINGS, IMAGES_PATH, PROMPT_PATH
from ..core.storage import now_iso, read_json, write_json
from .dataset_service import dataset_image_path, dataset_images_from, list_dataset_images
from .runtime_service import ensure_vllm_running

CATEGORY_LABELS = {
    "scene": "纯场景",
    "single_person": "单人",
    "multi_person": "多人",
    "object": "物品",
    "animal": "动物",
    "text_or_graphic": "文字/图形",
    "unknown": "未知",
}

CLOUD_SETTING_KEYS = {"type", "endpoint", "deployment", "apiVersion", "apiKey"}
LOCAL_SETTING_KEYS = {"type", "endpoint", "model"}


def pick_settings(source: dict[str, Any], keys: set[str]) -> dict[str, Any]:
    return {key: source.get(key) for key in keys if key in source}


def get_annotation_settings() -> dict[str, Any]:
    settings = read_json(ANNOTATION_SETTINGS_PATH, DEFAULT_ANNOTATION_SETTINGS)
    cloud = {**DEFAULT_ANNOTATION_SETTINGS.get("cloud", {}), **pick_settings(settings.get("cloud") or {}, CLOUD_SETTING_KEYS)}
    local = {**DEFAULT_ANNOTATION_SETTINGS.get("local", {}), **pick_settings(settings.get("local") or {}, LOCAL_SETTING_KEYS)}
    merged = {
        **DEFAULT_ANNOTATION_SETTINGS,
        **settings,
        "cloud": cloud,
        "local": local,
    }
    cloud = merged.get("cloud") or {}
    api_key = str(cloud.get("apiKey") or "")
    merged["cloud"] = {**cloud, "apiKey": "", "apiKeyConfigured": bool(api_key)}
    return merged


def get_annotation_settings_for_runtime() -> dict[str, Any]:
    settings = read_json(ANNOTATION_SETTINGS_PATH, DEFAULT_ANNOTATION_SETTINGS)
    return {
        **DEFAULT_ANNOTATION_SETTINGS,
        **settings,
        "cloud": {**DEFAULT_ANNOTATION_SETTINGS.get("cloud", {}), **pick_settings(settings.get("cloud") or {}, CLOUD_SETTING_KEYS)},
        "local": {**DEFAULT_ANNOTATION_SETTINGS.get("local", {}), **pick_settings(settings.get("local") or {}, LOCAL_SETTING_KEYS)},
    }


def save_annotation_settings(body: dict[str, Any]) -> dict[str, Any]:
    current = get_annotation_settings_for_runtime()
    cloud = body.get("cloud") if isinstance(body.get("cloud"), dict) else None
    if cloud is not None:
        cloud = pick_settings(cloud, CLOUD_SETTING_KEYS)
    if cloud is not None and not str(cloud.get("apiKey") or "").strip():
        cloud = {**cloud, "apiKey": (current.get("cloud") or {}).get("apiKey") or ""}
    settings = {
        **current,
        **{key: value for key, value in body.items() if key in {"provider", "local"}},
        **({"cloud": {**(current.get("cloud") or {}), **cloud}} if cloud is not None else {}),
    }
    write_json(ANNOTATION_SETTINGS_PATH, settings)
    return get_annotation_settings()


def extract_json_object(text: str) -> dict[str, Any]:
    stripped = text.strip()
    if stripped.startswith("```"):
        stripped = re.sub(r"^```(?:json)?\s*", "", stripped)
        stripped = re.sub(r"\s*```$", "", stripped)
    try:
        return json.loads(stripped)
    except json.JSONDecodeError:
        match = re.search(r"\{.*\}", stripped, re.S)
        if not match:
            raise
        return json.loads(match.group(0))


def normalize_category(value: Any) -> str:
    text = str(value or "").strip().lower()
    aliases = {
        "纯场景": "scene",
        "场景": "scene",
        "scene": "scene",
        "landscape": "scene",
        "单人": "single_person",
        "人物": "single_person",
        "single_person": "single_person",
        "single person": "single_person",
        "person": "single_person",
        "多人": "multi_person",
        "multi_person": "multi_person",
        "multiple people": "multi_person",
        "people": "multi_person",
        "物品": "object",
        "object": "object",
        "动物": "animal",
        "animal": "animal",
        "文字/图形": "text_or_graphic",
        "文字": "text_or_graphic",
        "text": "text_or_graphic",
        "graphic": "text_or_graphic",
    }
    return aliases.get(text, "unknown")


def image_data_url(file_path) -> str:
    content = file_path.read_bytes()
    encoded = base64.b64encode(content).decode("ascii")
    return f"data:image/jpeg;base64,{encoded}"


def annotation_prompt(dataset: dict[str, Any] | None = None) -> str:
    base_prompt = PROMPT_PATH.read_text(encoding="utf-8") if PROMPT_PATH.exists() else ""
    trigger = (dataset or {}).get("trigger") or "custom_trigger"
    return f"""{base_prompt}

请对图片做 LLM 语义分类和 caption 建议。只输出 JSON，不要输出 Markdown。
分类字段 category 必须是以下英文枚举之一：
- scene: 纯场景，没有明确主体人物
- single_person: 单人或单个主要人物主体
- multi_person: 多人
- object: 物品或非人物主体
- animal: 动物主体
- text_or_graphic: 主要是文字、图表、字幕页、UI 或图形
- unknown: 无法判断

输出 JSON schema：
{{
  "category": "scene | single_person | multi_person | object | animal | text_or_graphic | unknown",
  "category_label": "中文分类名",
  "subject": "主要主体，未知则写未知",
  "scene_type": "室内 / 室外 / 景观 / 物品特写 / 人物肖像 / 抽象 / 未知",
  "people_count": 0,
  "view_angle": "正面 / 侧面 / 三分之二视角 / 远景 / 局部细节 / 未知",
    "quality_score": 0,
    "training_suggestion": "选中 | 低权重 | 仅作风格参考 | 剔除",
    "caption_suggestion": "以 {trigger} 开头的中文 caption 建议，详细但精确描述主体、姿态动作、服饰外观、构图视角、场景物件、光线色彩和风格特征",
  "tags": ["中文标签"],
    "reject_reasons": [],
  "warnings": []
}}

规则：caption 和质量分数都只是建议，不代表用户已经接受；不要自动剔除图片。quality_score 必须是 0-100 的整数。caption_suggestion 要写可复现的视觉信息，不要只写泛化短句，也不要编造图片中不可见的身份、情节、品牌或来源。"""


def call_azure_openai(image_url: str, prompt: str, settings: dict[str, Any]) -> dict[str, Any]:
    cloud = settings.get("cloud") or {}
    endpoint = str(cloud.get("endpoint") or "").rstrip("/")
    deployment = str(cloud.get("deployment") or "gpt-4o")
    api_version = str(cloud.get("apiVersion") or "2024-10-21")
    api_key = str(cloud.get("apiKey") or "")
    if not endpoint:
        raise RuntimeError("Cloud 标注 endpoint 未配置")
    if not api_key:
        raise RuntimeError("Cloud 标注 API key 未配置")
    url = f"{endpoint}/openai/deployments/{deployment}/chat/completions?api-version={api_version}"
    body = {
        "messages": [
            {"role": "system", "content": "你是严谨的图片数据集标注助手。必须只输出 JSON。"},
            {
                "role": "user",
                "content": [
                    {"type": "text", "text": prompt},
                    {"type": "image_url", "image_url": {"url": image_url}},
                ],
            },
        ],
        "temperature": 0.0,
        "max_tokens": 900,
    }
    request = urllib.request.Request(
        url,
        data=json.dumps(body).encode("utf-8"),
        headers={
            "Content-Type": "application/json",
            "api-key": api_key,
        },
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=90) as response:
            payload = json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as error:
        detail = error.read().decode("utf-8", errors="replace")
        raise RuntimeError(f"Azure OpenAI 调用失败：HTTP {error.code} {detail}") from error
    content = payload["choices"][0]["message"]["content"]
    parsed = extract_json_object(content)
    parsed["_raw"] = content
    parsed["_model"] = deployment
    return parsed


def call_local_openai(image_url: str, prompt: str, settings: dict[str, Any]) -> dict[str, Any]:
    local = settings.get("local") or {}
    endpoint = str(local.get("endpoint") or "").rstrip("/")
    model = str(local.get("model") or "Qwen/Qwen2.5-VL-7B-Instruct")
    if not endpoint:
        raise RuntimeError("本地 vLLM endpoint 未配置")
    url = f"{endpoint}/chat/completions"
    body = {
        "model": model,
        "messages": [
            {"role": "system", "content": "你是严谨的图片数据集标注助手。必须只输出 JSON。"},
            {
                "role": "user",
                "content": [
                    {"type": "text", "text": prompt},
                    {"type": "image_url", "image_url": {"url": image_url}},
                ],
            },
        ],
        "temperature": 0.0,
        "max_tokens": 900,
    }
    request = urllib.request.Request(
        url,
        data=json.dumps(body).encode("utf-8"),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=180) as response:
            payload = json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as error:
        detail = error.read().decode("utf-8", errors="replace")
        raise RuntimeError(f"本地 vLLM 调用失败：HTTP {error.code} {detail}") from error
    except urllib.error.URLError as error:
        raise RuntimeError(f"本地 vLLM 连接失败：{error.reason}") from error
    content = payload["choices"][0]["message"]["content"]
    parsed = extract_json_object(content)
    parsed["_raw"] = content
    parsed["_model"] = model
    return parsed


def annotate_dataset_images(
    dataset_id: str,
    body: dict[str, Any] | None = None,
    should_cancel: Any | None = None,
    on_progress: Callable[[dict[str, Any]], None] | None = None,
) -> dict[str, Any]:
    body = body or {}
    settings = get_annotation_settings_for_runtime()
    provider = body.get("provider") or settings.get("provider") or "cloud"
    if provider not in {"cloud", "local"}:
        raise RuntimeError(f"不支持的标注供应商：{provider}")
    if provider == "local":
        ensure_vllm_running(wait_ready=True)

    image_ids = set(body.get("imageIds") or [])
    limit = int(body.get("limit") or 0)
    rows = list_dataset_images(dataset_id)
    if image_ids:
        rows = [image for image in rows if image.get("id") in image_ids]
    if limit > 0:
        rows = rows[:limit]
    if not rows:
        raise RuntimeError("没有可标注的图片")

    images = read_json(IMAGES_PATH, [])
    by_id = {image.get("id"): image for image in images}
    updated = 0
    failed: list[dict[str, Any]] = []
    results: list[dict[str, Any]] = []
    datasets = read_json(DATASETS_PATH, [])
    dataset = next((item for item in datasets if item.get("id") == dataset_id), None)
    prompt = annotation_prompt(dataset)

    total = len(rows)
    processed = 0
    for row in rows:
        if should_cancel and should_cancel():
            return {"images": dataset_images_from(images, dataset_id), "updated": updated, "failed": failed, "results": results, "cancelled": True, "settings": {"provider": provider, "cloudDeployment": (settings.get("cloud") or {}).get("deployment"), "localModel": (settings.get("local") or {}).get("model"), "localEndpoint": (settings.get("local") or {}).get("endpoint")}}
        image_id = row.get("id")
        try:
            file_path = dataset_image_path(dataset_id, row)
            parsed = call_local_openai(image_data_url(file_path), prompt, settings) if provider == "local" else call_azure_openai(image_data_url(file_path), prompt, settings)
            category = normalize_category(parsed.get("category") or parsed.get("category_label"))
            quality_score = parsed.get("quality_score") or parsed.get("质量分数") or parsed.get("qualityScore")
            try:
                quality_score = max(0, min(100, round(float(quality_score))))
            except (TypeError, ValueError):
                quality_score = None
            annotation = {
                "provider": provider,
                "model": ((settings.get("local") or {}).get("model") if provider == "local" else (settings.get("cloud") or {}).get("deployment")) or parsed.get("_model"),
                "runAt": now_iso(),
                "category": category,
                "categoryLabel": CATEGORY_LABELS.get(category, "未知"),
                "subject": parsed.get("subject") or parsed.get("主体") or "未知",
                "sceneType": parsed.get("scene_type") or parsed.get("场景") or "未知",
                "peopleCount": parsed.get("people_count"),
                "viewAngle": parsed.get("view_angle") or parsed.get("视角") or "未知",
                "qualityScore": quality_score,
                "trainingSuggestion": parsed.get("training_suggestion") or parsed.get("训练建议") or "选中",
                "captionSuggestion": parsed.get("caption_suggestion") or parsed.get("中文caption建议") or "",
                "rejectReasons": parsed.get("reject_reasons") or parsed.get("剔除原因") or [],
                "tags": parsed.get("tags") or [],
                "warnings": parsed.get("warnings") or [],
                "raw": {key: value for key, value in parsed.items() if not key.startswith("_")},
            }
            image = by_id.get(image_id)
            if not image:
                raise RuntimeError(f"图片记录不存在：{image_id}")
            image["llmClassification"] = annotation
            if annotation["qualityScore"] is not None:
                image["qualityScore"] = annotation["qualityScore"]
            image["quality"] = "已评分" if annotation["qualityScore"] is not None else image.get("quality", "未检查")
            if annotation["captionSuggestion"]:
                image["suggestion"] = annotation["captionSuggestion"]
            if not image.get("captionLocked"):
                if annotation["captionSuggestion"]:
                    image["caption"] = annotation["captionSuggestion"]
                image["annotation"] = "已标注"
            image["updatedAt"] = now_iso()
            updated += 1
            results.append({"id": image_id, "llmClassification": annotation})
        except Exception as error:
            failed.append({"id": image_id, "error": str(error)})
        processed += 1
        write_json(IMAGES_PATH, images)
        if on_progress:
            on_progress({"processed": processed, "total": total, "updated": updated, "failed": failed, "imageId": image_id})
    write_json(IMAGES_PATH, images)
    return {"images": dataset_images_from(images, dataset_id), "updated": updated, "failed": failed, "results": results, "settings": {"provider": provider, "cloudDeployment": (settings.get("cloud") or {}).get("deployment"), "localModel": (settings.get("local") or {}).get("model"), "localEndpoint": (settings.get("local") or {}).get("endpoint")}}
