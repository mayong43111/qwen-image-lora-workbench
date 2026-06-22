# Qwen Image LoRA Workbench

Qwen Image LoRA Workbench is a local-first dataset preparation and training operations UI for building Qwen Image LoRA datasets. It helps you collect video frames or images, run objective local screening, ask an annotation agent for captions and semantic labels, review final training captions, prepare LoRA training manifests, and track test generation requests.

The project is designed for a workstation or GPU VM workflow: prepare and review data locally, then move the generated manifests and run records to a GPU machine for training and evaluation.

## Features

- Dataset registry with trigger tokens, image counts, training selection, and caption status.
- Video import, local path import, download task creation, ffmpeg probing, and frame extraction.
- Manual image upload into a dataset.
- Local image screening for objective validity checks such as near-black frames, white frames, and low-information blur.
- Agent annotation through a configurable prompt, currently supporting Azure OpenAI GPT-4o via Azure CLI token auth.
- Caption review workflow with original suggestion and editable final training caption kept separate.
- Tags, category, quality score, annotation status, and training selection filters.
- LoRA training preparation that writes a manifest and training config under `local-data/training-runs/`.
- LoRA version registry with status, recommended strength, and weight path management.
- Evaluation request registry with prompt settings, per-seed result slots, result image import, and result image serving.
- Model and GPU status page backed by local API checks for NVIDIA GPU, Docker/vLLM, model directories, and musubi-tuner.

## Tech Stack

- Frontend: Vite, React 18, Ant Design 5, Ant Design Pro Components, React Router.
- Backend: FastAPI, Uvicorn, Pillow, local JSON registry files.
- Runtime tools: ffmpeg for probing/extraction, optional yt-dlp/aria2 for downloads, Azure CLI for cloud annotation auth.

## Repository Layout

```text
qwen-image-lora-workbench/
  docs/                     Product and UI design notes
  scripts/                  Deployment and operations scripts
  server/app/               FastAPI application
    core/                   Config, storage, process helpers, responses
    routers/                API routes
    services/               Dataset, video, task, annotation, training, model services
  src/                      React application
  index.html
  package.json
  requirements.txt
  vite.config.js
```

## Quick Start

Install Node and Python dependencies:

```powershell
npm install
python -m pip install -r requirements.txt
```

Start the local API and Vite dev server:

```powershell
npm run dev:all
```

Open:

```text
http://127.0.0.1:5174
```

You can also run the services separately:

```powershell
npm run api
npm run dev
```

## Local Data

The API stores local runtime state under `local-data/`. This directory is intentionally ignored by Git.

```text
local-data/
  registry/
    datasets.json
    videos.json
    images.json
    tasks.json
    annotation-prompt.txt
    annotation-settings.json
    loras.json
    evaluations.json
  datasets/
  videos/
  training-runs/
  evaluation-runs/
```

Training preparation writes:

```text
local-data/training-runs/<run_id>/dataset_manifest.jsonl
local-data/training-runs/<run_id>/train_config.json
```

Evaluation preparation writes:

```text
local-data/evaluation-runs/<run_id>/generation_request.json
```

## Annotation

The annotation page edits the prompt stored at `local-data/registry/annotation-prompt.txt`. The current cloud annotation service reads that prompt, appends the dataset trigger token and structured JSON constraints, and calls Azure OpenAI.

Default Azure settings are stored in `server/app/core/config.py` and can be overridden through `local-data/registry/annotation-settings.json`.

The expected annotation output includes semantic category, subject, scene type, people count, view angle, 0-100 quality score, caption suggestion, tags, and warnings. The quality score is produced by the annotation agent, not by local screening.

## Model And GPU Checks

The Models / GPU page calls:

```text
GET /api/models/status
GET /api/models/checks/{asset_id}
```

It checks for:

- NVIDIA GPU through `nvidia-smi`.
- Docker and `docker.io/vllm/vllm-openai:v0.23.0`.
- Qwen Image DiT, VAE, and text encoder directories under `/data/models/`.
- Qwen2.5-VL-7B annotation model under `/data/models/qwen2.5-vl-7b-instruct`.
- musubi-tuner under `/opt/musubi-tuner`.

These checks report local readiness. They do not start training or inference by themselves.

## Azure GPU VM Deployment

The repository includes a deployment helper for a North Europe Spot A100 VM:

```powershell
./scripts/deploy-northeurope-a100-spot.ps1 `
  -ResourceGroup rg-qwen-lora-neu `
  -VmName vm-qwen-lora-a100 `
  -ImageResourceGroup RG-AI-IMAGE-NORTHEUROPE `
  -Layer2ImageName ai-a100-layer2-orchestrator-ubuntu2204-202606201236 `
  -AdminUsername azureuser `
  -SshPublicKeyPath $env:USERPROFILE\.ssh\id_rsa.pub
```

The source image must be available in the same Azure region as the VM. Managed images are regional; if your layer2 image exists only in another region, replicate it first or pass a Shared Image Gallery version ID through `-ImageId`.

The script creates a Spot `Standard_NC24ads_A100_v4` VM by default, installs runtime packages through cloud-init, pulls the pinned vLLM image, downloads configurable Hugging Face model assets, clones musubi-tuner, installs the workbench, and registers local systemd services.

Use `-HuggingFaceToken` when the selected model repositories require authentication.

## API Shape

Most JSON APIs return:

```json
{
  "statusCode": 200,
  "message": "success",
  "data": {}
}
```

Image and video file endpoints return file responses directly.

## Validation

Common checks before committing:

```powershell
python -m compileall server\app
npm run build
```

## Project Status

This is an active local workbench. Dataset preparation, annotation review, training manifest preparation, LoRA registry, evaluation request tracking, and model/GPU readiness checks are implemented. Full Qwen Image LoRA training and generation runners are expected to execute on a GPU VM using the generated local artifacts.
