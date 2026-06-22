# Qwen Image LoRA Workbench V2 UI

这是 V2 的本地前端实现目录。当前阶段使用 Vite + React + Ant Design + ProComponents 搭建 Ant Design Pro 风格骨架，不连接远程服务器，也不会触发 GPU 训练或 VLM 标注。

## 目录

```text
qwen-image-lora-workbench/
  index.html
  package.json
  requirements.txt
  vite.config.js
  server/
    app/
      core/
      routers/
      services/
      main.py
    local_api.py
  src/
    main.jsx
    App.jsx
    styles.css
  docs/
    PRODUCT_DESIGN_V2.md
    WEB_UI_DESIGN_V2.md
```

## 本地运行

首次运行先安装依赖：

```powershell
npm install
python -m pip install -r requirements.txt
```

本地 API 使用 Python + FastAPI，默认监听 `http://127.0.0.1:8787`。视频导入识别只调用本机 `ffmpeg -i` 并解析输出。必须确保 `ffmpeg` 在 VS Code 启动环境的 `PATH` 中。普通链接下载需要额外安装 `yt-dlp`；磁力链接解析和下载需要安装 `aria2`，或设置 `ARIA2C_PATH` 指向 `aria2c`。

后端按模块拆分：`core/` 放路径、存储、进程工具和统一响应；`services/` 放数据集、视频、任务等业务逻辑；`routers/` 放 FastAPI 路由。除视频文件流接口外，JSON API 统一返回：

```json
{
  "statusCode": 200,
  "message": "success",
  "data": {}
}
```

启动开发服务器：

```powershell
npm run dev:all
```

然后访问：

```text
http://127.0.0.1:5174
```

也可以分别启动：

```powershell
npm run api
npm run dev
```

## 当前实现范围

已完成 Ant Design Pro 风格骨架和 Python + FastAPI 本地 API：

- Dashboard 简化总览
- 使用 `react-router-dom` 路由，不再用单个 App 内状态切换页面
- Videos 支持选择本地视频、导入本地路径或创建下载任务；抽帧时选择目标数据集
- 不再提供独立 Images 菜单；必须从 Dataset 进入 `/datasets/:datasetId` 查看该数据集图片
- Datasets 数据集、caption 工作区和 DatasetBuild 入口
- Datasets / Dataset Detail 显示训练资源预估：图片数量主要影响训练时间和 steps，显存主要由模型、分辨率、batch、精度和优化策略决定
- Annotation 中文标注任务入口，标注提示词直接显示，可手动修改
- Training 训练向导和训练监控面板
- LoRA Versions 版本列表
- Evaluation 测试生成配置和图片结果查看，不做评分
- Models & GPU 状态面板
- Tasks 异步任务列表

FastAPI 本地 API 当前已接入这些 CPU 阶段能力：

- Dataset 文件状态管理
- 视频导入 / 下载资源管理
- ffmpeg 自动识别视频时长、分辨率和 FPS
- ffmpeg 抽帧任务入口
- 抽帧 manifest 导入图片资产索引
- 图片按 Dataset 查看
- 中文标注提示词本地保存
- 任务队列与状态轮询

LLM/VLM 标注和 Qwen Image LoRA 训练保留入口，等本地 GPU/vLLM/musubi 运行条件满足后接入。

## CPU 阶段本地数据

FastAPI 本地 API 会把状态写到：

```text
qwen-image-lora-workbench/local-data/
  registry/
    datasets.json
    videos.json
    images.json
    tasks.json
    annotation-prompt.txt
  datasets/
```

这些文件是本地工作状态，不需要远程服务器。
