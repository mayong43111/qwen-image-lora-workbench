# Qwen Image LoRA 工作台 V2 Web UI 设计文档

## 1. UI 设计目标

Web UI 的核心不是展示脚本输出，而是把一组本地脚本、本地模型、视频资源、图片资源、数据集、训练任务和 LoRA 版本组织成可长期使用的工作台。

用户应能通过页面完成以下闭环：

```text
准备素材 -> 抽帧/上传图片 -> 标注图片 -> 筛选图片 -> 构建数据集 -> 选择模型训练 LoRA -> 测试 LoRA -> 管理版本
```

页面应始终围绕三个对象展开：

```text
Dataset：用户真正管理的训练目标，例如 A 视频飞船、B 视频画风、C 视频人物
Model：基础模型和标注模型，例如 Qwen Image 2512、Qwen2.5-VL-7B/32B
LoRA Version：某次训练产出的可测试、可对比、可归档版本
```

## 2. 信息架构

### 2.1 顶层导航

建议使用左侧固定导航。导航应偏工作台风格，强调状态和任务，不做营销式首页。

```text
Dashboard
Videos
Images
Datasets
Annotation
Training
LoRA Versions
Evaluation
Models & GPU
Tasks
Settings
```

### 2.2 全局顶部栏

顶部栏显示当前运行环境和关键状态：

- 当前基础模型：`Qwen Image 2512`
- 当前 VLM 标注模型：`Qwen/Qwen2.5-VL-7B-Instruct` 或 `Qwen/Qwen2.5-VL-32B-Instruct`
- GPU 状态：空闲、vLLM 标注中、训练中、测试生成中
- 当前活跃任务数量
- 备份/恢复入口

### 2.3 页面通用模式

所有资源页面采用一致的三段结构：

```text
顶部工具栏：创建、导入、批处理、筛选、搜索
主体列表/网格：资源状态、缩略图、关键字段、进度
右侧详情面板：元数据、日志、操作、关联对象
```

详情面板应支持固定宽度，避免页面跳动。长日志、长 caption、JSON 元数据使用可折叠区域。

## 3. Dashboard

Dashboard 是工作状态总览，不是介绍页。

### 3.1 关键卡片

```text
Active Dataset
Active Training Run
Latest LoRA Version
GPU / vLLM Status
Task Queue
Dataset Health
```

每张卡片展示可行动信息：

- 当前数据集选中图片数、未标注图片数、低质量风险数
- 当前训练进度、ETA、最新 checkpoint/LoRA 输出
- 最新 LoRA 的测试评分和推荐权重
- vLLM 是否占用 GPU，训练前是否需要释放
- 下载、抽帧、标注、训练、测试生成任务进度

### 3.2 快捷动作

```text
Add Video
Extract Frames
Annotate Unlabeled Images
Create Dataset
Build Training Dataset
Start Training
Run LoRA Test
```

快捷动作应根据当前状态启用或禁用。例如没有 DatasetBuild 时，`Start Training` 禁用并提示先构建训练输入。

## 4. Videos 页面

Videos 管理可重复抽帧的视频资源。一个视频不是一个数据集，它只是图片来源。

### 4.1 视频列表

字段：

```text
thumbnail
title
source_type
duration
resolution
fps
download_status
extraction_job_count
image_count
last_used_at
tags
```

列表支持筛选：

- 下载中、可用、失败、已删除
- 磁力、HTTP、本地上传、本地路径
- 已抽帧、未抽帧
- 关联到哪些 Dataset

### 4.2 添加视频

添加入口支持：

```text
Magnet Link
HTTP/HTTPS URL
Local Path
Upload File
```

提交后创建异步任务。页面展示下载进度、速度、ETA、已下载大小和日志。

### 4.3 抽帧面板

抽帧是 Videos 页面最重要的交互。

布局：

```text
视频预览区
时间轴范围选择器：start_sec / end_sec
抽帧设置：fixed interval / scene change / manual range
频率输入：每 N 秒一帧
预计输出：预计图片数、预计磁盘占用
目标：只生成全局 ImageAsset，不直接绑定 Dataset
启动按钮：Start Extraction
```

交互要求：

- 用户可以拖动起点和终点。
- 时间轴需要显示当前帧缩略预览。
- 修改抽帧频率时实时更新预计图片数。
- 同一个视频允许多次抽帧，每次生成独立 `FrameExtractionJob`。
- 抽帧完成后提示进入 Images 页面查看结果。

## 5. Images 页面

Images 是全局图片资产库。图片可以来自视频抽帧，也可以来自上传或导入。

### 5.1 图片网格

默认使用密集图片网格，支持缩略图、多选和快速筛选。

每个图片单元显示：

```text
thumbnail
selected badge if selected in current DatasetBuild
annotation status badge
quality badge
source badge: video / upload / generated / imported
warning badges: black, blurry, subtitle, watermark, duplicate
```

### 5.2 筛选器

筛选器应分组显示：

```text
Source
- video source
- extraction job
- upload/import/generated

Annotation
- basic not started/running/done/failed
- VLM not started/running/done/failed/stale
- manual reviewed/locked

Quality
- black screen
- blurry
- subtitle-heavy
- watermark
- duplicate
- low quality score

Domain
- domain_type
- target visibility
- view angle
- subtype
- structure/identity/style quality
- training role suggestion

Dataset
- in dataset
- selected
- excluded
- caption locked
```

### 5.3 图片详情面板

详情面板包含：

```text
Preview
Source Info
Basic Metadata
Quality Metadata
VLM Annotation
Domain Metadata
Caption Suggestion
Human Caption
Dataset Memberships
Action Log
```

用户可以在详情里：

- 修改 selected 状态。
- 修改领域标签、视角、子类型、训练角色。
- 接受、编辑或重写 caption。
- 锁定 caption，防止后续自动覆盖。
- 对单张图片重新运行基础标注或 VLM 标注。
- 查看图片属于哪些 Dataset。

### 5.4 批量操作

批量操作入口：

```text
Run Basic Annotation
Run VLM Annotation
Re-run VLM Annotation
Add to Dataset
Remove from Dataset
Mark Selected
Mark Excluded
Lock Captions
Apply Caption Template
Export Selection
```

重要原则：元数据只辅助用户选择，不应自动强制删除或强制加入训练。

## 6. Datasets 页面

Datasets 是用户管理训练目标的核心页面。不同目标应创建不同数据集，而不是把它们理解成同一个数据集的版本。

示例：

```text
A 视频飞船结构 Dataset
B 视频画风 Dataset
C 视频人物 Dataset
上传产品图 Object Dataset
景观风格 Landscape Dataset
```

### 6.1 数据集列表

字段：

```text
name
domain_type
trigger_token
image_count
selected_count
unannotated_count
caption_locked_count
latest_build
latest_lora
status
updated_at
```

### 6.2 创建数据集

创建表单：

```text
Dataset Name
Domain Type: character / landscape / object / vehicle / architecture / style / mixed / custom
Training Goal
Trigger Token
Global Style Description
Caption Guidelines
Default Selection Policy
Default Evaluation Prompt Set
```

`Global Style Description` 和 `Caption Guidelines` 可以由用户手写，也可以请求 LLM 给建议；最终保存内容必须是用户确认后的文本。

### 6.3 数据集详情

详情页分为 Tabs：

```text
Overview
Images
Captions
Builds
Training Runs
LoRA Versions
Evaluation
Settings
```

Overview 展示：

- 图片数量、选中数量、未标注数量、低质量数量。
- 领域分布、视角分布、子类型分布、来源视频分布。
- caption 来源分布：manual、LLM suggested approved、template。
- 最近 DatasetBuild、TrainingRun 和 LoRA Version。

### 6.4 Dataset Images Tab

这是针对当前 Dataset 的图片工作区。

能力：

- 从全局 Images 池添加候选图片。
- 依据标注筛选当前数据集候选图片。
- 快速剔除黑屏、纯字幕、模糊、低质量图片。
- 按人物/物品角度、可见性、构图、结构质量筛选。
- 批量 selected/excluded。
- 保留人工覆盖结果。

页面应明确显示：

```text
Selected images will be used for training.
Excluded images will not be used.
Metadata helps filtering but does not force the decision.
```

### 6.5 Captions Tab

caption 是训练输入的一部分，应有独立编辑体验。

表格字段：

```text
thumbnail
current_caption
caption_source
caption_locked
caption_suggestion
warnings
selected
```

操作：

- 批量生成 LLM caption 建议。
- 批量应用统一 caption 模板。
- 单张图片编辑 caption。
- 接受 LLM 建议为最终 caption。
- 锁定人工 caption。
- 检查是否缺少 trigger token。
- 检查 caption 是否过短、过泛或包含不应出现的来源名。

### 6.6 Builds Tab

DatasetBuild 是从 Dataset 导出的不可变训练输入快照。

创建 Build 时应展示确认页面：

```text
selected image count
train/eval split
caption policy
missing caption count
unannotated image count
quality risk count
domain distribution
source video distribution
output manifest path
```

Build 状态：

```text
draft
locked
training
archived
```

Build 一旦 locked，不应被修改；如需调整，用户应回到 Dataset Images/Captions 修改后创建新的 Build。

## 7. Annotation 页面

Annotation 页面用于集中管理标注任务，避免用户必须从单张图片入口操作。

### 7.1 标注队列

视图：

```text
Unannotated Images
Failed Annotation
Stale Annotation
Manual Review Needed
Locked Captions
```

### 7.2 启动标注

启动 VLM 标注前，页面需要选择：

```text
Model: Qwen/Qwen2.5-VL-7B-Instruct or Qwen/Qwen2.5-VL-32B-Instruct
Dataset context: optional Dataset, used to provide domain prompt
Prompt template: domain_annotation_v1 or custom
Scope: selected images / current filter / current dataset / all unannotated
Overwrite policy: skip existing / re-run stale / force overwrite suggestions only
```

标注输出写入结构化元数据和 caption_suggestion，不直接覆盖用户锁定的 caption。

### 7.3 标注结果审核

审核页面应支持键盘快速操作：

```text
accept suggestion
edit caption
mark selected
mark excluded
flag wrong annotation
rerun VLM
next image
```

## 8. Training 页面

Training 页面只负责训练 LoRA，不负责临时拼数据。训练输入应来自 locked DatasetBuild。

### 8.1 训练启动向导

训练启动分四步：

```text
1. Select DatasetBuild
2. Select Base Model: Qwen Image 2512
3. Configure Training
4. Review & Start
```

### 8.2 Step 1：选择 DatasetBuild

显示：

```text
Dataset name
Build name
selected image count
caption completeness
domain distribution
created_at
previous training runs
```

如果 Build 不是 locked，禁止训练并提示用户先锁定 Build。

### 8.3 Step 2：选择模型

基础模型选择默认是 `Qwen Image 2512`。

需要展示：

```text
DiT path
VAE path
Text encoder path
trainer: musubi-tuner
generation script availability
LoRA support
```

### 8.4 Step 3：训练配置

常用配置默认展开：

```text
training preset
output name
network rank / dim
network alpha
learning rate
epochs or max_train_steps
batch size
resolution
seed
save interval
```

高级配置折叠：

```text
optimizer
lr scheduler
repeats / image weights
bucket settings
mixed precision
gradient checkpointing
fp8 options
blocks to swap
cache latents
cache text encoder outputs
save state
resume from state
sample prompts during training
stop vLLM before training
restore vLLM after training
```

### 8.5 Step 4：启动前检查

启动前检查：

```text
DatasetBuild locked
all selected images exist
captions present
base model files exist
trainer exists
GPU available
vLLM status checked
enough disk space
resume state valid if provided
```

如果 vLLM 正在运行，页面提供：

```text
Stop vLLM and start training
Cancel
```

### 8.6 训练监控

训练运行后展示：

```text
status
current epoch
current step / total steps
loss if available
ETA
GPU memory
latest log lines
latest checkpoint
latest LoRA output
pause/cancel if supported
```

训练完成后提供：

```text
View LoRA Version
Run Evaluation
Start Another Training From This Build
Resume From State
```

## 9. LoRA Versions 页面

LoRA Versions 页面管理训练产物，不把 checkpoint、训练任务和最终 LoRA 混在一起。

### 9.1 列表字段

```text
name
base_model
dataset
dataset_build
training_run
epoch
step
file_size
recommended_strength
status: candidate / approved / rejected / archived
latest_eval_score
created_at
```

### 9.2 LoRA 详情

详情页显示：

- 来源 Dataset 和 DatasetBuild。
- 训练参数。
- 训练日志。
- 输出文件路径。
- 推荐 LoRA 权重。
- 历史测试结果。
- 人工备注和状态。

操作：

```text
Run Evaluation
Compare With Another Version
Mark Approved
Mark Rejected
Archive
Copy Generation Config
```

## 10. Evaluation 页面

Evaluation 用于验证 `Qwen Image 2512 + 指定 LoRA 版本` 的效果。

### 10.1 测试启动

输入：

```text
Base Model: Qwen Image 2512
LoRA Version: one or more
Prompt Set: dataset default / custom
LoRA Weight
Resolution
Steps
Guidance Scale
Seed
Batch Count
```

Prompt Set 应来自 Dataset 的评测模板，也允许用户临时新增测试 prompt。

### 10.2 对比视图

对比视图支持：

```text
same prompt across LoRA versions
same seed across LoRA versions
base model without LoRA baseline
LoRA weight sweep
side-by-side grid
rating and notes
```

### 10.3 评分维度

默认评分维度：

```text
target_match
style_match
identity_or_structure_consistency
prompt_control
artifact_level
generic_prior_drift
overall_rating
```

评分结果写回 LoRA Version，用于版本筛选和 approved/rejected 决策。

## 11. Models & GPU 页面

### 11.1 模型管理

模型分为：

```text
Base image model: Qwen Image 2512
VLM annotation model: Qwen2.5-VL-7B/32B
Text encoder
VAE
Trainer runtime
```

每个模型显示路径、存在性检查、大小、最近使用时间和健康状态。

### 11.2 vLLM 控制

能力：

```text
Start vLLM
Stop vLLM
Health Check
Select annotation model
View endpoint
View logs
```

训练开始前，UI 应明确提示 vLLM 会占用 GPU，需要关闭释放显存。

### 11.3 GPU 状态

显示：

```text
GPU name
driver/CUDA
memory used/free
active process
current workload: idle / vLLM / training / evaluation
```

## 12. Tasks 页面

Tasks 是所有异步任务的统一监控中心。

### 12.1 任务类型

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

### 12.2 任务列表字段

```text
kind
status
progress percent
current/total
ETA
started_at
duration
related resource
latest log line
```

任务详情页展示完整输入、输出、日志、错误、重试入口和取消入口。

## 13. Settings 页面

Settings 管理路径、默认模型和行为偏好。

配置项：

```text
workspace root
dataset root
video storage path
image storage path
model paths
musubi-tuner path
python/venv path
default base model
default VLM model
default extraction interval
default caption policy
default training preset
backup path
```

## 14. 关键状态规则

### 14.1 图片状态

图片本身状态和数据集成员状态分开：

```text
ImageAsset lifecycle: active / hidden / deleted
Basic annotation: not_started / running / done / failed
VLM annotation: not_started / running / done / failed / stale
Manual review: unreviewed / reviewed / locked
Dataset membership: candidate / selected / excluded
Caption: missing / suggested / edited / locked
```

### 14.2 DatasetBuild 状态

```text
draft: 可继续调整输入
locked: 可用于训练，不可修改
training: 已被训练任务占用
archived: 保留复盘，不再作为默认选择
```

### 14.3 LoRA Version 状态

```text
candidate: 新训练产物，等待测试
approved: 用户认可，可作为推荐版本
rejected: 测试不达标，不推荐使用
archived: 历史保留
```

## 15. 推荐实现顺序

1. Dashboard、Tasks、Settings 的基础框架。
2. Videos 页面：视频资源管理、磁力/HTTP 任务、抽帧面板。
3. Images 页面：全局图片库、筛选、详情、基础元数据展示。
4. Annotation 页面：启动本地 VLM 标注、标注状态和 caption suggestion。
5. Datasets 页面：创建 Dataset、选择图片、编辑 caption、创建 DatasetBuild。
6. Training 页面：选择 DatasetBuild + Qwen Image 2512，配置并启动 LoRA 训练。
7. LoRA Versions 页面：管理训练产物和版本状态。
8. Evaluation 页面：运行 `Qwen Image 2512 + LoRA 指定版本` 测试并对比结果。
9. Models & GPU 页面：vLLM 启停、GPU 状态和训练前释放显存流程。