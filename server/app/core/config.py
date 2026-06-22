from __future__ import annotations

from pathlib import Path

SERVER_DIR = Path(__file__).resolve().parents[2]
PROJECT_ROOT = SERVER_DIR.parent
WORKBENCH_SCRIPTS_DIR = PROJECT_ROOT / "scripts"
REPO_ROOT = PROJECT_ROOT
DATA_ROOT = PROJECT_ROOT / "local-data"
DATA_DIR = DATA_ROOT / "registry"
DATASETS_PATH = DATA_DIR / "datasets.json"
VIDEOS_PATH = DATA_DIR / "videos.json"
IMAGES_PATH = DATA_DIR / "images.json"
TASKS_PATH = DATA_DIR / "tasks.json"
LORAS_PATH = DATA_DIR / "loras.json"
EVALUATIONS_PATH = DATA_DIR / "evaluations.json"
PROMPT_PATH = DATA_DIR / "annotation-prompt.txt"
ANNOTATION_SETTINGS_PATH = DATA_DIR / "annotation-settings.json"
TRAINING_RUNS_DIR = DATA_ROOT / "training-runs"
EVALUATION_RUNS_DIR = DATA_ROOT / "evaluation-runs"
EXTRACT_SCRIPT = WORKBENCH_SCRIPTS_DIR / "extract_frames.py"
CLASSIFY_SCRIPT = WORKBENCH_SCRIPTS_DIR / "classify_frames.py"
VIDEOS_DIR = DATA_ROOT / "videos"

DEFAULT_PROMPT = """你是用于构建 Qwen Image LoRA 数据集的中文图片标注助手。

请只输出 JSON，不要输出 Markdown。字段和值尽量使用中文。

目标：根据当前数据集上下文，标注这张图片是否适合进入训练，并给出可供用户编辑的中文 caption 建议。

必须包含字段：
{
  "主体": "图片中的主要人物、景观、物品或风格主体",
  "场景": "室内 / 室外 / 景观 / 物品特写 / 人物肖像 / 抽象 / 未知",
  "视角": "正面 / 侧面 / 三分之二视角 / 远景 / 局部细节 / 未知",
  "质量分数": 0,
  "训练建议": "选中 / 低权重 / 仅作风格参考 / 剔除",
  "中文caption建议": "必须以 trigger token 开头，用一到两句详细但精确地描述可见主体、姿态动作、服饰外观、构图视角、场景物件、光线色彩和风格特征",
  "剔除原因": []
}

规则：
- 不要提到电影名、来源视频名、演员名、品牌名或版权角色名。
- 如果不确定，使用“未知”，不要猜测。
- 质量分数必须是 0-100 的整数：清晰、主体明确、构图稳定、对训练有帮助的图片给高分；黑屏、严重模糊、遮挡严重、字幕/文字页、重复或低信息量给低分。
- 中文caption建议必须详细但精确，优先包含：主体类型、可见外观、姿态或动作、表情、镜头距离、构图、视角、场景、关键物件、光线、色彩和画面风格；不要写图片里看不到的身份、情节或主观评价。
- 如果图片用于人物或风格 LoRA，caption 应描述可复现的视觉特征，而不是只写“一名人物在室内”这类泛化短句。
- caption 只是建议，最终由用户手动确认。"""

DEFAULT_ANNOTATION_SETTINGS = {
  "provider": "cloud",
  "cloud": {
    "type": "azure-openai",
    "resourceGroup": "rg-auto-gen-chat",
    "accountName": "aif-auto-gen-chat",
    "endpoint": "https://aif-auto-gen-chat.cognitiveservices.azure.com/",
    "deployment": "gpt-4o",
    "apiVersion": "2024-10-21",
    "auth": "azure-cli-token",
  },
  "local": {
    "type": "openai-compatible",
    "endpoint": "http://127.0.0.1:8000/v1",
    "model": "/data/models/qwen2.5-vl-7b-instruct",
  },
}

