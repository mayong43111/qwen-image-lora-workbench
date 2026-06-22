# Qwen Image LoRA 工作台 V2 设计文档

## 1. 设计目标

本应用是一个通过 UI 控制本地脚本和本地模型的 Qwen Image LoRA 工作台。核心目标不是单次脚本执行，而是长期管理：视频资源、图片资源、数据集、LoRA 版本、训练任务、测试生成任务和标注状态。

应用应围绕三个层级组织能力：

```text
核心能力：选择数据集 + 选择基础模型 + 训练 LoRA + 管理 LoRA 版本 + 测试 LoRA 效果
边缘能力：从视频/上传图片生成可训练数据集，支持标注、筛选、重标注和人工选择
基础能力：下载、vLLM 模型服务、异步任务监控、GPU 资源释放与恢复
```

本设计是全新 V2 设计，不要求兼容当前实现。重点是数据结构、数据集元数据设计和图片标注 LLM prompt 设计。

## 2. 产品边界

### 2.1 核心能力

1. 通过 UI 选择基础模型，例如 Qwen Image 2512。
2. 通过 UI 选择一个数据集，构建训练输入，启动 LoRA 训练。
3. 管理多个数据集，例如 A 视频抽取飞船、B 视频抽取画风、C 视频抽取人物。数据集之间是不同训练目标，不是同一个数据集的简单版本。
4. 管理多个 LoRA 版本，包括训练参数、来源数据集、训练日志、输出文件和测试图。
5. 使用指定基础模型 + 指定 LoRA 版本生成测试图片，验证 LoRA 效果。

### 2.2 边缘能力

1. 管理视频资源，支持一个视频被反复抽帧。
2. 在页面上选择视频时间范围和抽帧频率，生成图片资源。
3. 支持上传独立图片，图片可以没有视频来源。
4. 管理图片资源，一张图片可以属于多个数据集。
5. 使用 ffmpeg/OpenCV 进行基础元数据标注。
6. 使用本地 VLM，例如 `Qwen/Qwen2.5-VL-7B-Instruct` 或 `Qwen/Qwen2.5-VL-32B-Instruct` 补全语义、结构、质量和训练建议。
7. 支持图片标注状态、选择状态、重标注状态和人工审核状态。
8. 元数据用于辅助筛选，而不是强制约束；用户可以覆盖自动判断。

### 2.3 基础能力

1. 磁力链接和 HTTP/HTTPS 视频下载。
2. vLLM 模型启动、停止、健康检查和模型选择。
3. 训练前自动关闭 VLM/vLLM 标注服务以释放 GPU。
4. 任务监控：下载、抽帧、基础标记、VLM 标注、数据集构建、训练、测试生成。
5. 支持任务取消、重试、续跑和日志查看。

## 3. 核心概念模型

V2 中应把“视频、图片、数据集、训练、LoRA、测试生成”拆成独立实体。

```text
VideoAsset
  -> FrameExtractionJob
    -> ImageAsset

UploadedImage
  -> ImageAsset

ImageAsset
  -> ImageAnnotation
  -> DatasetMembership

Dataset
  -> DatasetBuild
    -> TrainingRun
      -> LoraVersion
        -> LoraEvaluationRun
```

关键原则：

- 图片是全局资产，不直接等同于数据集。
- 数据集是面向某个训练目标的图片集合，例如风格、人物、景观、物品或飞船结构。
- DatasetBuild 是训练前从数据集导出的不可变快照，用于复盘某次训练输入；它不是用户主要理解的“数据集版本”。
- 图片元数据和数据集成员状态分开。
- LoRA 版本必须记录来源 Dataset、DatasetBuild 和训练参数。
- 测试生成必须记录基础模型、LoRA 版本、prompt、seed、参数和输出图片。

## 4. 存储布局建议

V2 可以继续使用文件系统作为主状态存储，所有状态文件用 JSON/JSONL/TOML，便于恢复、备份和人工审查。

```text
/opt/ai-workbench/qwen-lora-workbench/
  registry/
    videos.jsonl
    images.jsonl
    datasets.jsonl
    loras.jsonl
    models.jsonl
    tasks.jsonl

  videos/
    <video_id>/
      source/<original_file>
      metadata.json
      thumbnails/

  images/
    <image_id_prefix>/
      <image_id>.jpg
      <image_id>.metadata.json
      <image_id>.annotations.jsonl

  datasets/
    <dataset_id>/
      dataset.json
      builds/
        <dataset_build_id>/
          manifest.jsonl
          dataset_card.md
          split_train.jsonl
          split_eval.jsonl
          captions/

  training_runs/
    <training_run_id>/
      config.toml
      command.sh
      logs/train.log
      checkpoints/
      output/

  loras/
    <lora_id>/
      lora.json
      versions/
        <lora_version_id>/
          model.safetensors
          metadata.json
          eval/

  eval_runs/
    <eval_run_id>/
      request.json
      outputs/
      report.json
```

## 5. 数据结构设计

### 5.1 VideoAsset

视频资源是可重复抽帧的原始素材。一个视频可以对应多个抽帧任务和多个图片集合。

```json
{
  "video_id": "vid_20260621_0001",
  "title": "movie_or_source_name",
  "source_type": "magnet | http | upload | local_path",
  "source_uri": "magnet:?xt=...",
  "local_path": "videos/vid_20260621_0001/source/input.mp4",
  "sha256": "...",
  "bytes": 123456789,
  "duration_sec": 7240.5,
  "width": 1920,
  "height": 1080,
  "fps": 24.0,
  "codec": "h264",
  "created_at": "2026-06-21T00:00:00Z",
  "status": "available | downloading | failed | deleted",
  "tags": ["source-video", "candidate-dataset"],
  "notes": ""
}
```

### 5.2 FrameExtractionJob

抽帧任务不是简单地覆盖图片目录，而是一次可追踪的数据生成动作。

```json
{
  "job_id": "extract_20260621_0001",
  "video_id": "vid_20260621_0001",
  "start_sec": 120.0,
  "end_sec": 620.0,
  "interval_sec": 2.0,
  "mode": "fixed_interval | scene_change | manual_range",
  "output_image_ids": ["img_..."],
  "created_at": "2026-06-21T00:00:00Z",
  "status": "queued | running | succeeded | failed | cancelled",
  "progress": {
    "current": 120,
    "total": 250,
    "text": "120/250 frames"
  }
}
```

### 5.3 ImageAsset

图片是全局资产。它可以来自视频抽帧，也可以来自上传。

```json
{
  "image_id": "img_01H...",
  "source_type": "video_frame | upload | generated | imported",
  "file_path": "images/ab/img_01H....jpg",
  "sha256": "...",
  "bytes": 123456,
  "width": 1920,
  "height": 818,
  "format": "jpg",
  "created_at": "2026-06-21T00:00:00Z",

  "video_ref": {
    "video_id": "vid_20260621_0001",
    "timestamp_sec": 455.0,
    "frame_index": 10920,
    "extraction_job_id": "extract_20260621_0001"
  },

  "upload_ref": {
    "original_filename": null,
    "uploaded_by": "local_user"
  },

  "lifecycle": {
    "status": "active | hidden | deleted",
    "duplicate_of": null
  }
}
```

### 5.4 ImageMetadata

图片元数据分为基础元数据、技术质量、语义标注、领域结构标注、caption 建议和人工覆盖。

元数据不是训练硬约束，而是帮助用户筛选。用户可以手动覆盖自动判断。

```json
{
  "image_id": "img_01H...",
  "metadata_version": "v2",
  "updated_at": "2026-06-21T00:00:00Z",

  "basic": {
    "width": 1920,
    "height": 818,
    "aspect_ratio": 2.35,
    "brightness_mean": 0.42,
    "brightness_std": 0.18,
    "sharpness_laplacian": 132.4,
    "phash": "..."
  },

  "quality": {
    "quality_score": 0.82,
    "reject_reasons": [],
    "risk_tags": ["subtitle_light"],
    "is_black": false,
    "is_white_flash": false,
    "is_blurry": false,
    "is_duplicate": false,
    "has_watermark": false,
    "has_subtitle": false
  },

  "semantic": {
    "main_subjects": ["primary subject", "environment", "secondary object"],
    "scene_type": "interior | exterior | landscape | object_closeup | portrait | vehicle | abstract | unknown",
    "style_tags": ["cinematic", "hard surface", "industrial design"],
    "composition_tags": ["wide shot", "three quarter view"],
    "caption_suggestion": "trigger_token, subject type, view angle, major structure, visual style...",
    "caption_notes": "LLM suggestion only; final caption can be edited or replaced by the user."
  },

  "domain": {
    "domain_type": "character | landscape | object | vehicle | architecture | style | mixed | unknown",
    "contains_target_subject": true,
    "target_subject_count": 1,
    "target_visibility": "full | partial | tiny | occluded | background_only | unknown",
    "view_angle": "front | side | top | rear | three_quarter | close_detail | scene | unknown",
    "subtype": "domain-specific subtype or unknown",
    "structure_quality": "clear | partial | occluded | tiny | generic_risk | unknown",
    "structure_tags": [
      "domain-specific structural feature 1",
      "domain-specific structural feature 2"
    ],
    "generic_prior_risk": 0.25,
    "training_role_suggestion": "structure | detail | scene | style_only | identity | reject"
  },

  "annotation_state": {
    "basic_done": true,
    "vlm_done": true,
    "vlm_model": "Qwen/Qwen2.5-VL-7B-Instruct",
    "vlm_prompt_version": "domain_annotation_v1",
    "manual_reviewed": false,
    "needs_reannotation": false
  },

  "manual_override": {
    "selected": null,
    "view_angle": null,
    "subtype": null,
    "training_role": null,
    "caption": null,
    "notes": ""
  }
}
```

### 5.5 Dataset

Dataset 是一个独立训练目标，例如“从 A 视频抽取的飞船结构数据集”、“从 B 视频抽取的画风数据集”、“从 C 视频抽取的人物数据集”。不同训练目标应建成不同数据集，而不是塞进同一个数据集下当版本。

```json
{
  "dataset_id": "ds_a_video_target_subject",
  "name": "A Video Target Subject Dataset",
  "purpose": "Qwen Image 2512 LoRA for a specific subject, style, landscape, person, or object family",
  "domain_type": "character | landscape | object | vehicle | architecture | style | mixed",
  "trigger_token": "custom_trigger_token",
  "global_style_description": "Human-written dataset-level description. The LLM may suggest this, but the user owns the final wording.",
  "created_at": "2026-06-21T00:00:00Z",
  "status": "active | archived",
  "tags": ["qwen-image", "lora", "domain-specific"]
}
```

### 5.6 DatasetBuild

DatasetBuild 是训练前导出的不可变快照。用户主要管理的是不同 Dataset；Build 用于记录某次训练到底用了哪些图片、caption、全局说明和筛选规则，便于复盘和重复训练。

```json
{
  "dataset_build_id": "dsb_a_video_target_exp001",
  "dataset_id": "ds_a_video_target_subject",
  "build_name": "exp001",
  "created_at": "2026-06-21T00:00:00Z",
  "base_model_target": "Qwen Image 2512",
  "selection_policy": {
    "include_roles": ["structure", "detail", "style_only", "identity"],
    "exclude_quality": ["tiny", "occluded", "blurry", "black", "subtitle_heavy"],
    "balance_by": ["view_angle", "subtype", "source_video_id", "scene_type"],
    "allow_manual_override": true
  },
  "counts": {
    "total_images": 10000,
    "selected_images": 6400,
    "train_images": 6000,
    "eval_images": 400
  },
  "global_caption_prefix": "custom_trigger_token",
  "global_style_description": "Final human-approved dataset-level description used to guide captions and training.",
  "caption_policy": "manual | llm_suggested_user_approved | template_generated",
  "manifest_path": "datasets/ds_a_video_target_subject/builds/exp001/manifest.jsonl",
  "status": "draft | locked | training | archived"
}
```

### 5.7 DatasetMembership

一张图片可以属于多个数据集。选择状态属于某个 DatasetBuild，而不是图片本身。

```json
{
  "dataset_build_id": "dsb_a_video_target_exp001",
  "image_id": "img_01H...",
  "selected": true,
  "split": "train | eval | excluded",
  "selection_source": "auto | manual | imported",
  "selection_reason": ["structure_clear", "view_side", "subtype_selected_by_user"],
  "caption": "custom_trigger_token, human-approved caption for this image",
  "caption_source": "manual | llm_suggested_user_approved | template",
  "caption_locked": false,
  "weight": 1.0,
  "repeat": 1,
  "notes": ""
}
```

### 5.8 ModelProfile

基础模型和标注模型都应作为可选模型配置管理。

```json
{
  "model_profile_id": "qwen_image_2512_comfy",
  "kind": "image_base | vlm_annotation | text_encoder | vae",
  "name": "Qwen Image 2512",
  "provider": "local_file | huggingface | vllm",
  "paths": {
    "dit": "/opt/ai-workbench/models/qwen-image-comfy/split_files/diffusion_models/qwen_image_2512_bf16.safetensors",
    "vae": "/opt/ai-workbench/models/qwen-image-comfy/split_files/vae/qwen_image_vae.safetensors",
    "text_encoder": "/opt/ai-workbench/models/qwen-image-comfy/split_files/text_encoders/qwen_2.5_vl_7b.safetensors"
  },
  "runtime": {
    "trainer": "musubi-tuner",
    "supports_lora": true,
    "supports_generation": true
  }
}
```

### 5.9 TrainingRun

训练任务必须完整记录输入、参数、输出和恢复信息。

```json
{
  "training_run_id": "train_20260621_0001",
  "dataset_build_id": "dsb_a_video_target_exp001",
  "base_model_profile_id": "qwen_image_2512_comfy",
  "trainer": "musubi-tuner",
  "status": "queued | running | succeeded | failed | cancelled | interrupted",
  "params": {
    "training_preset": "structure_lora | style_lora | character_lora | object_lora | landscape_lora | custom",
    "network_module": "networks.lora_qwen_image",
    "network_dim": 64,
    "network_alpha": 64,
    "learning_rate": 0.00005,
    "lr_scheduler": "constant | cosine | linear | custom",
    "optimizer": "adamw8bit",
    "batch_size": 1,
    "gradient_accumulation_steps": 1,
    "epochs": 3,
    "max_train_steps": null,
    "resolution": [1024, 1024],
    "enable_bucket": true,
    "bucket_no_upscale": false,
    "num_repeats": 1,
    "mixed_precision": "bf16",
    "gradient_checkpointing": true,
    "fp8_base": false,
    "fp8_scaled": false,
    "blocks_to_swap": 0,
    "save_every_n_steps": 1000,
    "save_every_n_epochs": 1,
    "save_state": true,
    "sample_every_n_steps": null,
    "sample_prompts_path": null,
    "seed": 42
  },
  "resume": {
    "resume_supported": true,
    "resume_from": null,
    "latest_state_path": null,
    "latest_lora_path": null
  },
  "progress": {
    "current_step": 0,
    "total_steps": 0,
    "current_epoch": 0,
    "eta_sec": null
  },
  "outputs": {
    "lora_version_ids": [],
    "log_path": "training_runs/train_20260621_0001/logs/train.log"
  }
}
```

### 5.9.1 TrainingConfigOptions

训练页面应把配置分成“常用配置”和“高级配置”。默认可以来自训练模板，但用户需要能展开并覆盖关键参数。

```json
{
  "training_config_options": {
    "required": {
      "dataset_build_id": "DatasetBuild used as immutable training input",
      "base_model_profile_id": "Qwen Image base model profile",
      "output_name": "LoRA output name",
      "training_preset": "style_lora | character_lora | object_lora | landscape_lora | structure_lora | custom"
    },
    "common": {
      "network_dim": [16, 32, 64, 128],
      "network_alpha": [16, 32, 64, 128],
      "learning_rate": [0.00001, 0.00005, 0.0001],
      "epochs_or_steps": "epochs or max_train_steps",
      "resolution": [768, 1024, 1280],
      "batch_size": [1, 2, 4],
      "seed": "integer or random"
    },
    "advanced": {
      "optimizer": "adamw8bit | adamw | prodigy | custom",
      "lr_scheduler": "constant | cosine | linear | custom",
      "repeats_or_weights": "per image or per subset weighting",
      "bucket_settings": "enable_bucket, min_bucket_reso, max_bucket_reso, bucket_no_upscale",
      "precision": "bf16 | fp16 | fp32",
      "memory": "gradient_checkpointing, fp8_base, fp8_scaled, blocks_to_swap",
      "cache": "cache_latents, cache_text_encoder_outputs, cache_to_disk",
      "checkpointing": "save_every_n_steps, save_every_n_epochs, save_state",
      "resume": "resume_from state or checkpoint",
      "sampling": "sample_every_n_steps, sample_prompts, lora_multiplier sweep",
      "gpu_runtime": "stop_vllm_before_training, restore_vllm_after_training"
    }
  }
}
```

UI 默认只展示 required 和 common，advanced 作为可展开面板。每个训练模板可以带一组推荐默认值，例如风格 LoRA 更关注风格一致性，人物 LoRA 更关注身份稳定，结构/物品 LoRA 更关注视角和部件覆盖。

### 5.10 LoraVersion

LoRA 版本是训练产物，不等同于训练 checkpoint。

```json
{
  "lora_id": "lora_dataset_target",
  "lora_version_id": "lora_dataset_target_exp001_epoch02",
  "name": "Dataset LoRA exp001 epoch02",
  "base_model_profile_id": "qwen_image_2512_comfy",
  "dataset_id": "ds_a_video_target_subject",
  "dataset_build_id": "dsb_a_video_target_exp001",
  "training_run_id": "train_20260621_0001",
  "file_path": "loras/lora_dataset_target/versions/exp001_epoch02/model.safetensors",
  "bytes": 123456789,
  "created_at": "2026-06-21T00:00:00Z",
  "train_step": 2000,
  "epoch": 2,
  "recommended_strength": {
    "min": 0.8,
    "default": 1.0,
    "max": 1.2
  },
  "status": "candidate | approved | rejected | archived",
  "notes": "Better than epoch01, slight overfit on the dominant subtype."
}
```

### 5.11 LoraEvaluationRun

LoRA 测试生成是独立任务，必须可复盘。

```json
{
  "eval_run_id": "eval_20260621_0001",
  "lora_version_id": "lora_dataset_target_exp001_epoch02",
  "base_model_profile_id": "qwen_image_2512_comfy",
  "prompt_set_id": "dataset_eval_v1",
  "prompts": [
    "custom_trigger_token, prompt for the target dataset, plain background",
    "custom_trigger_token, prompt for the target dataset, cinematic composition"
  ],
  "generation_params": {
    "width": 1024,
    "height": 1024,
    "steps": 25,
    "guidance_scale": 4.0,
    "seed": 42,
    "lora_multiplier": 1.0
  },
  "outputs": [
    {
      "image_path": "eval_runs/eval_20260621_0001/outputs/0001.png",
      "prompt_index": 0,
      "seed": 42,
      "rating": null,
      "notes": ""
    }
  ],
  "status": "queued | running | succeeded | failed"
}
```

## 6. UI 设计

### 6.1 顶层导航

建议页面：

```text
Dashboard
Videos
Images
Datasets
Annotations
Training
LoRA Versions
Evaluation
Models / GPU
Tasks
Settings
```

### 6.2 Videos

能力：

- 添加磁力链接、HTTP 链接、本地路径或上传视频。
- 查看视频基本信息、下载状态、帧率、时长、分辨率。
- 打开抽帧面板：视频预览 + 起始/结束滑块 + 抽帧频率。
- 一个视频可创建多个抽帧任务。

抽帧 UI：

```text
video preview
timeline slider: start_sec / end_sec
interval_sec input
scene-change option
estimated frame count
start extraction button
```

### 6.3 Images

能力：

- 全局图片资源浏览。
- 按来源视频、抽帧任务、上传来源过滤。
- 按基础质量、VLM 标注状态、领域类型、视角、子类型、结构质量过滤。
- 支持批量启动基础标记、VLM 标注、重新标注。
- 支持人工修改元数据和选择状态。

### 6.4 Datasets

能力：

- 创建数据集，例如 `A 视频飞船结构`、`B 视频画风`、`C 视频人物`、`某产品物品 LoRA`。
- 定义 trigger token 和全局风格描述。
- 从图片池中按标签筛选候选图片。
- 支持人工选择/剔除。
- 生成不可变 DatasetBuild，作为一次训练输入快照。
- 查看每个 Build 的标签分布：领域类型、视角、子类型、结构质量、场景类型、来源视频。

### 6.5 Training

能力：

- 选择基础模型：Qwen Image 2512。
- 选择 DatasetBuild。
- 选择训练模板：结构 LoRA、风格 LoRA、人物 LoRA、物品 LoRA、景观 LoRA、细节 LoRA。
- 设置关键参数：rank、alpha、epochs/steps、learning rate、scheduler、optimizer、batch、分辨率、bucket、repeat、保存间隔、resume、显存优化。
- 启动训练前提示是否关闭 VLM/vLLM 标注服务释放 GPU。
- 显示训练日志、进度、ETA、GPU 使用、输出 LoRA。

### 6.6 LoRA Versions

能力：

- 查看 LoRA 版本列表。
- 显示来源 Dataset、DatasetBuild、训练参数、epoch/step、推荐强度。
- 标记 approved/rejected/candidate。
- 比较不同 LoRA 版本的测试生成结果。

### 6.7 Evaluation

能力：

- 选择 Qwen Image 2512 基础模型。
- 选择一个或多个 LoRA 版本。
- 选择固定 prompt set。
- 设置 seed、分辨率、steps、LoRA 权重。
- 生成对比图。
- 对输出图做人工评分和备注。

## 7. 图片标注流程设计

### 7.1 标注分层

图片标注分两步：

```text
基础标记：ffmpeg/OpenCV
  -> 尺寸、比例、亮度、清晰度、重复、黑屏、字幕风险

VLM 标注：Qwen2.5-VL-7B/32B
  -> 主体、场景、caption 建议、领域类型、视角、子类型、结构/身份/风格质量、训练建议
```

基础标记便宜，可以对所有图片跑。VLM 标注较贵，但更有语义价值，应支持只标注未标注图片，也支持强制重标注。

### 7.2 标注状态

每张图片应有独立状态：

```json
{
  "image_id": "img_...",
  "basic_status": "not_started | running | done | failed",
  "vlm_status": "not_started | running | done | failed | stale",
  "manual_status": "unreviewed | reviewed | locked",
  "selected_in_datasets": ["ds_a_video_target_subject"],
  "last_annotation_model": "Qwen/Qwen2.5-VL-7B-Instruct",
  "last_annotation_prompt_version": "domain_annotation_v1"
}
```

## 8. LLM/VLM 标注 Prompt 设计

### 8.1 Prompt 目标

VLM 标注不是为了写漂亮文案，而是为了生成可筛选、可训练、可复盘的结构化元数据。

输出必须：

- 使用固定 JSON schema。
- 对不确定内容使用 `unknown`，不要猜测过度。
- 区分结构学习图片、细节图片、场景图片、只适合风格图片和应剔除图片。
- 对目标领域的视角、子类型、结构/身份/风格质量做稳定分类。
- 给出用于 LoRA 训练的 caption 建议，但最终 caption 应由用户确认、编辑或重写。
- 不要把某一个示例领域写死；飞船、人物、景观、物品、建筑、画风都应通过可配置领域模板处理。

### 8.2 系统 Prompt：通用图片标注

```text
You are an image annotation model for building Qwen Image LoRA datasets.

Return only valid JSON. Do not include markdown.

Your job is to describe the image for dataset filtering and LoRA training. Be conservative. If a field is uncertain, use "unknown" or an empty array. Do not invent identities, brands, movie names, copyrighted character names, or source titles.

Focus on:
- technical image quality
- main subjects
- scene type
- composition
- whether the image is useful for LoRA training
- whether it should be rejected or reviewed

Use the dataset domain configuration to decide which fields matter most. For structure datasets, prioritize shape and components. For character datasets, prioritize identity-safe visual consistency and avoid naming real people. For style datasets, prioritize lighting, color, composition, rendering, and atmosphere. For object/product datasets, prioritize silhouette, parts, material, and view angle.
```

### 8.3 用户 Prompt：通用领域标注

```text
Analyze this image for a Qwen Image LoRA dataset.

Dataset domain: {domain_type}
Dataset goal: {dataset_goal}
Trigger token: {trigger_token}
Human-written global description: {global_style_description}

Important: captions are suggestions. The user may edit or replace them before training.

Return JSON with this exact schema:

{
  "contains_target_subject": boolean,
  "target_subject_count": number,
  "target_visibility": "full" | "partial" | "tiny" | "occluded" | "background_only" | "unknown",
  "view_angle": "front" | "side" | "top" | "rear" | "three_quarter" | "close_detail" | "scene" | "portrait" | "wide" | "unknown",
  "subtype": string,
  "structure_quality": "clear" | "partial" | "occluded" | "tiny" | "generic_risk" | "unknown",
  "structure_tags": string[],
  "identity_or_style_risk": number,
  "generic_prior_risk": number,
  "scene_type": "space" | "dockyard" | "interior" | "planet_orbit" | "surface" | "abstract" | "unknown",
  "composition_tags": string[],
  "style_tags": string[],
  "quality_score": number,
  "reject_reasons": string[],
  "training_role_suggestion": "structure" | "detail" | "scene" | "style_only" | "identity" | "reject",
  "caption_suggestion": string,
  "caption_warnings": string[],
  "notes": string
}

Rules:
- quality_score must be from 0.0 to 1.0.
- identity_or_style_risk and generic_prior_risk must be from 0.0 to 1.0.
- Use "unknown" if the view, subtype, or target subject is unclear.
- Use "tiny" if the target subject is too small for the intended learning goal.
- Use "generic_risk" when the image mostly matches the base model's common prior instead of the target dataset's distinctive concept.
- training_role_suggestion should match the dataset goal: structure, identity, style, detail, scene, or reject.
- caption_suggestion must start with the trigger token.
- caption_suggestion should describe the target learning goal first, then secondary style/composition.
- Do not mention source video, movie names, character names, brand names, or actor names.
```

### 8.4 领域模板示例

领域模板用于告诉 VLM 该看什么，不用于限制系统只能做某一类数据集。

```json
{
  "domain_type": "vehicle",
  "important_fields": ["view_angle", "subtype", "structure_quality", "structure_tags", "generic_prior_risk"],
  "subtype_examples": ["carrier", "interceptor", "cargo", "explorer"],
  "structure_tag_examples": ["wide central hull", "rear engine pods", "segmented armor"]
}
```

```json
{
  "domain_type": "character",
  "important_fields": ["identity_consistency", "pose", "clothing", "hair", "view_angle", "identity_or_style_risk"],
  "subtype_examples": ["full body", "half body", "portrait", "action pose"],
  "safety_rule": "Do not name real people or actors."
}
```

```json
{
  "domain_type": "landscape",
  "important_fields": ["scene_type", "composition_tags", "lighting", "terrain", "atmosphere"],
  "subtype_examples": ["mountain", "city", "coast", "forest", "alien planet"]
}
```

### 8.5 Caption 生成规则

caption 可以由用户手写，也可以由 LLM 给统一建议。最终进入训练的 caption 应由用户确认。系统不应自动把 LLM caption 当作不可修改事实。

通用 caption 应包含：

```text
trigger token
target subject or style category
view angle or composition when relevant
major structure / identity / style features based on dataset goal
secondary material, lighting, atmosphere, or rendering notes
```

推荐格式：

```text
custom_trigger_token, target subtype, clear view or composition, key features that match the dataset goal, secondary material or style notes, lighting or atmosphere
```

不推荐：

```text
custom_trigger_token, beautiful image, cinematic, detailed, epic
```

## 9. 数据集构建策略

### 9.1 筛选不是强制规则

自动元数据只辅助选择，不应替代用户判断。用户可以：

- 选择自动建议保留的图片。
- 剔除自动建议保留的图片。
- 保留自动建议剔除的图片。
- 修改标签和 caption。
- 对已标注图片强制重新标注。

### 9.2 数据集建议比例

比例不是固定规则，应由 Dataset 的训练目标决定。系统可以提供模板，用户最终确认。

结构/物品类 LoRA 示例：

```text
结构清晰主图：50-70%
局部结构细节：15-25%
场景/环境图：10-20%
纯风格图：0-10%
遮挡/太小/模糊/通用先验风险图：默认剔除或低权重
```

人物/角色类 LoRA 示例：

```text
身份清晰主图：45-65%
姿态/角度变化：20-35%
服饰/细节图：10-20%
场景图：0-10%
```

画风/景观类 LoRA 示例：

```text
代表性风格主图：50-70%
构图和光照变化：20-35%
主体变化样本：10-20%
低质量或风格不一致图：默认剔除或低权重
```

### 9.3 平衡采样维度

DatasetBuild 生成时应显示并允许用户调整分布：

```text
domain_type distribution
view_angle distribution
subtype distribution
structure_or_identity_quality distribution
scene_type distribution
caption_source distribution
video_source distribution
```

如果某一视频、某一主体子类型或某一种构图占比过高，应提示用户降采样，避免 LoRA 过拟合到单一来源或单一模式。

## 10. 任务系统设计

所有长操作都应是异步任务：

```text
download_video
extract_frames
basic_annotate_images
vlm_annotate_images
build_dataset
cache_training_dataset
train_lora
generate_lora_eval_images
backup_dataset
upload_to_blob
start_vllm_model
stop_vllm_model
```

任务字段：

```json
{
  "task_id": "task_...",
  "kind": "train_lora",
  "status": "queued | running | succeeded | failed | cancelled",
  "created_at": "2026-06-21T00:00:00Z",
  "started_at": null,
  "finished_at": null,
  "progress": {
    "current": 0,
    "total": 0,
    "percent": 0,
    "eta_sec": null,
    "text": ""
  },
  "input": {},
  "output": {},
  "log_path": "tasks/task_.../task.log",
  "pid": null,
  "cancel_requested": false
}
```

## 11. GPU 和 vLLM 管理

应用需要区分两类 GPU 工作负载：

```text
VLM 标注：Qwen2.5-VL-7B/32B via vLLM
LoRA 训练/测试生成：Qwen Image 2512 + LoRA via trainer/generation script
```

训练前策略：

- 检查 GPU 占用。
- 如果 vLLM 标注服务正在运行，提示用户关闭或自动关闭。
- 记录关闭前模型和参数，训练后可一键恢复。
- 防止 VLM 标注任务和训练任务同时抢同一块 GPU。

## 12. LoRA 测试设计

LoRA 测试不是临时生成图片，而是版本评估。

必须支持：

- 选择基础模型版本。
- 选择 LoRA 版本。
- 设置 LoRA 权重。
- 选择固定 prompt set。
- 固定 seed 生成可比较结果。
- 保存输出图、prompt、参数和人工评分。

固定测试集应来自 Dataset 的评测模板，而不是写死某个领域。不同数据集可以有不同 prompt set：

```text
custom_trigger_token, target subject, plain background, clear canonical view
custom_trigger_token, target subject, alternate view, controlled composition
custom_trigger_token, target subject, detail-focused prompt
custom_trigger_token, target style or identity in a different scene
custom_trigger_token, target concept with higher composition complexity
```

评分维度：

```text
structure_accuracy
style_match
view_consistency
subtype_control
artifact_level
generic_prior_drift
```

## 13. 后续实现优先级

建议按以下顺序实现：

1. 重构数据模型：VideoAsset、ImageAsset、Dataset、DatasetBuild、LoraVersion。
2. 建立图片全局资产库，不再把图片直接绑死在单一 source 目录。
3. 实现视频资源管理和可重复抽帧任务。
4. 实现图片基础元数据和 VLM 标注状态。
5. 实现通用领域 JSON 标注 prompt、领域模板和标注结果入库。
6. 实现 DatasetBuild 构建和按标签筛选/平衡采样。
7. 实现 LoRA 训练任务和 LoRA 版本管理。
8. 实现 LoRA 测试生成和版本对比报告。
