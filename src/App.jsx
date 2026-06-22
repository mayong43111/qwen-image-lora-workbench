import React, { useEffect, useRef, useState } from 'react';
import { Alert, Button, Col, Descriptions, Divider, Drawer, Form, Image, Input, InputNumber, List, Modal, Progress, Row, Select, Slider, Space, Steps, Tabs, Tag, Typography, message } from 'antd';
import { AppstoreOutlined, CloudServerOutlined, DatabaseOutlined, DownloadOutlined, FolderOpenOutlined, PlayCircleOutlined, ProfileOutlined, RocketOutlined, SettingOutlined, TagsOutlined, VideoCameraOutlined } from '@ant-design/icons';
import { PageContainer, ProCard, ProLayout, ProTable, StatisticCard } from '@ant-design/pro-components';
import { Navigate, Route, Routes, useLocation, useNavigate, useParams } from 'react-router-dom';

const { Text, Paragraph } = Typography;
const { TextArea } = Input;
const localApiOrigin = import.meta.env.VITE_LOCAL_API_ORIGIN || `${window.location.protocol}//${window.location.hostname}:8787`;

const route = {
  path: '/',
  routes: [
    { path: '/dashboard', name: '总览', icon: <AppstoreOutlined /> },
    { path: '/videos', name: '视频', icon: <VideoCameraOutlined /> },
    { path: '/datasets', name: '数据集', icon: <DatabaseOutlined /> },
    { path: '/annotation', name: '标注', icon: <TagsOutlined /> },
    { path: '/training', name: '训练', icon: <RocketOutlined /> },
    { path: '/loras', name: 'LoRA 版本', icon: <ProfileOutlined /> },
    { path: '/evaluation', name: '测试生成', icon: <PlayCircleOutlined /> },
    { path: '/models', name: '模型 / GPU', icon: <CloudServerOutlined /> },
    { path: '/tasks', name: '任务', icon: <SettingOutlined /> },
  ],
};

async function api(apiPath, options = {}) {
  const response = await fetch(apiPath, {
    headers: { 'Content-Type': 'application/json' },
    ...options,
  });
  const text = await response.text();
  const payload = text ? JSON.parse(text) : {};
  if (!response.ok) throw new Error(payload.message || payload.error || response.statusText);
  return payload && Object.prototype.hasOwnProperty.call(payload, 'data') ? payload.data : payload;
}

async function uploadVideo(file, title) {
  const params = new URLSearchParams({ filename: file.name, title: title || file.name });
  const response = await fetch(`${localApiOrigin}/api/videos/import-file?${params.toString()}`, { method: 'POST', body: file });
  const text = await response.text();
  const payload = text ? JSON.parse(text) : {};
  if (!response.ok) throw new Error(payload.message || payload.error || response.statusText);
  return payload && Object.prototype.hasOwnProperty.call(payload, 'data') ? payload.data : payload;
}

async function uploadDatasetImage(datasetId, file) {
  const params = new URLSearchParams({ filename: file.name });
  const response = await fetch(`${localApiOrigin}/api/datasets/${datasetId}/images/import-file?${params.toString()}`, { method: 'POST', body: file });
  const text = await response.text();
  const payload = text ? JSON.parse(text) : {};
  if (!response.ok) throw new Error(payload.message || payload.error || response.statusText);
  return payload && Object.prototype.hasOwnProperty.call(payload, 'data') ? payload.data : payload;
}

async function uploadEvaluationResult(evaluationId, resultId, file) {
  const params = new URLSearchParams({ filename: file.name });
  const response = await fetch(`${localApiOrigin}/api/evaluations/${evaluationId}/results/${resultId}/import-file?${params.toString()}`, { method: 'POST', body: file });
  const text = await response.text();
  const payload = text ? JSON.parse(text) : {};
  if (!response.ok) throw new Error(payload.message || payload.error || response.statusText);
  return payload && Object.prototype.hasOwnProperty.call(payload, 'data') ? payload.data : payload;
}

function evaluationResultImageUrl(result) {
  if (!result?.imageUrl) return '';
  return String(result.imageUrl).startsWith('/api/') ? `${localApiOrigin}${result.imageUrl}` : result.imageUrl;
}

function statusTag(status) {
  const colorMap = {
    可用: 'green', 可训练: 'green', 已标注: 'green', 完成: 'green', 镜像已就绪: 'green', 候选: 'blue', 运行中: 'processing',
    等待中: 'default', 等待GPU: 'blue', 等待GPU训练: 'blue', 等待GPU生成: 'blue', 训练中: 'processing', 下载中: 'processing', 整理中: 'orange', 待识别: 'orange', 待确认: 'blue', 未检查: 'orange', 未标注: 'orange', 未安装: 'orange', 未就绪: 'orange',
    需复核: 'orange', 缺少标注: 'red', 缺失: 'red', 低质量: 'red', 失败: 'red', 已取消: 'default', 归档: 'default',
  };
  return <Tag color={colorMap[status] || 'default'}>{status || '未知'}</Tag>;
}

function screeningLabelTag(label) {
  const labelMap = {
    black_frame: { text: '黑屏', color: 'red' },
    black_or_near_black: { text: '黑屏/接近黑屏', color: 'red' },
    white_or_flash: { text: '白屏/闪白', color: 'red' },
    low_information: { text: '低信息量', color: 'orange' },
    blurry_motion: { text: '模糊/低信息量', color: 'orange' },
  };
  const item = labelMap[label] || { text: label, color: 'default' };
  return <Tag color={item.color}>{item.text}</Tag>;
}

function normalizeScreeningLabel(label) {
  const aliases = { black_frame: 'black_or_near_black', low_information: 'blurry_motion' };
  return aliases[label] || label;
}

function screeningIssueLabels(image) {
  return (image.localScreening?.labels || [])
    .map(normalizeScreeningLabel)
    .filter((label) => label !== 'usable_style_candidate');
}

function imageCategoryTag(category) {
  const labelMap = {
    scene: { text: '纯场景', color: 'cyan' },
    single_person: { text: '单人', color: 'blue' },
    multi_person: { text: '多人', color: 'purple' },
    object: { text: '物品', color: 'geekblue' },
    animal: { text: '动物', color: 'gold' },
    text_or_graphic: { text: '文字/图形', color: 'orange' },
    unknown: { text: '待LLM分类', color: 'default' },
  };
  const item = labelMap[category || 'unknown'] || { text: category, color: 'default' };
  return <Tag color={item.color}>{item.text}</Tag>;
}

function imageCategoryValue(image) {
  return image.llmClassification?.category || image.category || 'unknown';
}

function annotationStatusValue(image) {
  return image?.annotation === '已标注' ? '已标注' : '未标注';
}

function metadataText(value) {
  if (Array.isArray(value)) return value.length ? value.join('、') : '-';
  return value ?? '-';
}

function imageTags(image) {
  const tags = image?.llmClassification?.tags || image?.tags || [];
  if (Array.isArray(tags)) return tags.filter(Boolean);
  return String(tags || '').split(/[、,，\s]+/).filter(Boolean);
}

function imageQualityScore(image) {
  const value = image?.llmClassification?.qualityScore;
  if (typeof value === 'number') return Math.round(value);
  if (value !== undefined && value !== null && value !== '' && !Number.isNaN(Number(value))) return Math.round(Number(value));
  return null;
}

function qualityScoreBand(score) {
  if (score === null || score === undefined) return 'unscored';
  if (score >= 80) return 'high';
  if (score >= 60) return 'medium';
  return 'low';
}

function qualityScoreTag(score) {
  if (score === null || score === undefined) return <Text type="secondary">-</Text>;
  const color = score >= 80 ? 'green' : score >= 60 ? 'orange' : 'red';
  return <Tag color={color}>{score}</Tag>;
}

function trainingSelectedValue(image) {
  return image?.selected !== false;
}

function datasetName(datasets, datasetId) {
  return datasets.find((item) => item.id === datasetId)?.name || datasetId;
}

function formatSeconds(value) {
  return (Math.round((Number(value) || 0) * 10) / 10).toFixed(1);
}

function estimateTrainingResource(dataset) {
  const imageCount = dataset.selectedImages || 0;
  const steps = Math.ceil(imageCount * 3);
  const hours = imageCount < 250 ? '约 1-3 小时' : imageCount < 600 ? '约 3-8 小时' : '约 8 小时以上';
  return {
    imageCount,
    steps,
    hours,
    vram: 'A100 80GB 推荐；显存主要取决于模型、分辨率、batch、精度和显存优化，不随图片数量线性增长。',
    note: '图片数量主要影响训练步数、训练时间、缓存体积和过拟合风险。',
  };
}

function preferredTrainingDataset(datasets) {
  return datasets.find((item) => (item.selectedImages || 0) > 0) || datasets[0];
}

function TrainingResourceHint({ dataset }) {
  const estimate = estimateTrainingResource(dataset);
  return <Alert type="info" showIcon message={`训练资源预估：${estimate.imageCount} 张已选图片，建议约 ${estimate.steps} steps，${estimate.hours}`} description={<Space direction="vertical" size={4}><Text>{estimate.vram}</Text><Text type="secondary">{estimate.note}</Text></Space>} />;
}

function useLocalData() {
  const [data, setData] = useState({ datasets: [], videos: [], tasks: [], loras: [], evaluations: [], loading: true, error: null });
  async function refresh() {
    setData((value) => ({ ...value, loading: true, error: null }));
    try {
      const [datasetPayload, videoPayload, taskPayload, loraPayload, evaluationPayload] = await Promise.all([api('/api/datasets'), api('/api/videos'), api('/api/tasks'), api('/api/loras'), api('/api/evaluations')]);
      setData({ datasets: datasetPayload.datasets || [], videos: videoPayload.videos || [], tasks: taskPayload.tasks || [], loras: loraPayload.loras || [], evaluations: evaluationPayload.evaluations || [], loading: false, error: null });
    } catch (error) {
      setData({ datasets: [], videos: [], tasks: [], loras: [], evaluations: [], loading: false, error: error.message });
    }
  }
  useEffect(() => { refresh(); }, []);
  return { ...data, refresh };
}

function DashboardPage({ datasets, tasks, loras: loraRows, apiError }) {
  const runningTasks = tasks.filter((item) => item.status === '运行中').length;
  return <PageContainer title="总览" subTitle="只显示核心数量。"><div className="page-stack">{apiError ? <Alert type="warning" showIcon message="本地 API 未连接" description={apiError} /> : null}<div className="simple-dashboard"><StatisticCard statistic={{ title: '数据集数量', value: datasets.length }} /><StatisticCard statistic={{ title: 'LoRA 数量', value: loraRows.length }} /><StatisticCard statistic={{ title: '运行中任务', value: runningTasks }} /></div></div></PageContainer>;
}

function VideosPage({ datasets, videos, refresh }) {
  const [importForm] = Form.useForm();
  const [pathForm] = Form.useForm();
  const [downloadForm] = Form.useForm();
  const navigate = useNavigate();
  const [addOpen, setAddOpen] = useState(false);
  const [magnetFiles, setMagnetFiles] = useState([]);
  const [selectedMagnetFiles, setSelectedMagnetFiles] = useState([]);
  const [magnetLoading, setMagnetLoading] = useState(false);
  const [magnetError, setMagnetError] = useState('');
  const [downloadUrl, setDownloadUrl] = useState('');
  const [loadedMagnetUrl, setLoadedMagnetUrl] = useState('');
  const isMagnetDownload = downloadUrl.trim().toLowerCase().startsWith('magnet:?');

  useEffect(() => {
    const value = downloadUrl.trim();
    if (!value.toLowerCase().startsWith('magnet:?')) return undefined;
    if (value === loadedMagnetUrl) return undefined;
    const timer = window.setTimeout(() => loadMagnetFiles(value), 600);
    return () => window.clearTimeout(timer);
  }, [downloadUrl, loadedMagnetUrl]);

  async function importSelectedFile(values) {
    const file = values.file?.[0];
    if (!file) return message.warning('请选择本地视频文件');
    try {
      const payload = await uploadVideo(file, values.title);
      importForm.resetFields();
      if (payload.video?.status === '待识别') {
        message.warning(`视频已导入，元数据待识别：${payload.video.metadataError}`);
      } else {
        message.success('已导入视频并识别元数据');
      }
      setAddOpen(false);
      refresh();
    } catch (error) {
      message.error(`导入视频失败：${error.message}`);
    }
  }

  async function importByPath(values) {
    try {
      const payload = await api('/api/videos/import', { method: 'POST', body: JSON.stringify(values) });
      pathForm.resetFields();
      if (payload.video?.status === '待识别') {
        message.warning(`视频已导入，元数据待识别：${payload.video.metadataError}`);
      } else {
        message.success('已导入本地路径视频并识别元数据');
      }
      setAddOpen(false);
      refresh();
    } catch (error) {
      message.error(`导入路径失败：${error.message}`);
    }
  }

  async function downloadVideo(values) {
    if (isMagnetDownload && !selectedMagnetFiles.length) {
      return message.warning('请先选择磁力链接中要下载的文件');
    }
    try {
      const selectedFileDetails = magnetFiles.filter((item) => selectedMagnetFiles.includes(item.index));
      await api('/api/videos/download', { method: 'POST', body: JSON.stringify({ ...values, selectedFiles: selectedMagnetFiles, selectedFileDetails }) });
      downloadForm.resetFields();
      setDownloadUrl('');
      setMagnetFiles([]);
      setSelectedMagnetFiles([]);
      setMagnetError('');
      message.success('已创建视频下载任务');
      setAddOpen(false);
      refresh();
    } catch (error) {
      message.error(`创建下载任务失败：${error.message}`);
    }
  }

  async function loadMagnetFiles(url) {
    const value = String(url || '').trim();
    setDownloadUrl(value);
    setMagnetFiles([]);
    setSelectedMagnetFiles([]);
    setMagnetError('');
    if (!value.toLowerCase().startsWith('magnet:?')) {
      setLoadedMagnetUrl('');
      return;
    }
    setLoadedMagnetUrl(value);
    setMagnetLoading(true);
    try {
      const payload = await api('/api/videos/magnet/files', { method: 'POST', body: JSON.stringify({ url: value }) });
      const files = payload.files || [];
      setMagnetFiles(files);
      if (files.length === 1) setSelectedMagnetFiles([files[0].index]);
    } catch (error) {
      setMagnetError(error.message);
    } finally {
      setMagnetLoading(false);
    }
  }

  function closeAddVideoModal() {
    setAddOpen(false);
    setDownloadUrl('');
    setMagnetFiles([]);
    setSelectedMagnetFiles([]);
    setMagnetError('');
    setLoadedMagnetUrl('');
  }

  const addVideoTabs = [
    {
      key: 'file',
      label: <Space><FolderOpenOutlined />选择本地</Space>,
      children: (
        <Form form={importForm} layout="vertical" onFinish={importSelectedFile}>
          <Form.Item name="file" label="本地视频文件" valuePropName="files" getValueFromEvent={(event) => Array.from(event.target.files || [])} rules={[{ required: true, message: '请选择视频文件' }]}>
            <Input type="file" accept="video/*" />
          </Form.Item>
          <Form.Item name="title" label="视频名"><Input placeholder="默认使用文件名，可手动修改" /></Form.Item>
          <Button type="primary" htmlType="submit">导入视频</Button>
        </Form>
      ),
    },
    {
      key: 'path',
      label: '本地路径',
      children: (
        <Form form={pathForm} layout="vertical" onFinish={importByPath}>
          <Form.Item name="localPath" label="本地视频路径" rules={[{ required: true }]}><Input placeholder="D:\\videos\\input.mp4" /></Form.Item>
          <Form.Item name="title" label="视频名"><Input placeholder="默认使用文件名，可手动修改" /></Form.Item>
          <Button type="primary" htmlType="submit">导入路径</Button>
        </Form>
      ),
    },
    {
      key: 'download',
      label: <Space><DownloadOutlined />下载视频</Space>,
      children: (
        <Form form={downloadForm} layout="vertical" onFinish={downloadVideo}>
          <Form.Item name="url" label="视频下载地址 / 磁力链接" rules={[{ required: true }]}>
            <TextArea rows={3} placeholder="https://... 或 magnet:?xt=urn:btih:..." onBlur={(event) => loadMagnetFiles(event.target.value)} onChange={(event) => setDownloadUrl(event.target.value)} />
          </Form.Item>
          {isMagnetDownload ? (
            <div className="magnet-file-panel">
              <div className="magnet-file-header">
                <Text strong>磁力文件列表</Text>
                <Button size="small" onClick={() => loadMagnetFiles(downloadForm.getFieldValue('url'))} loading={magnetLoading}>重新加载</Button>
              </div>
              {magnetError ? <Alert type="warning" showIcon message="文件列表加载失败" description={magnetError} /> : null}
              {!magnetError && !magnetFiles.length ? <Alert type="info" showIcon message={magnetLoading ? '正在加载文件列表' : '粘贴磁力链接后会自动加载文件列表'} /> : null}
              {magnetFiles.length ? (
                <List
                  className="magnet-file-list"
                  size="small"
                  loading={magnetLoading}
                  dataSource={magnetFiles}
                  renderItem={(item) => (
                    <List.Item>
                      <label className="magnet-file-row">
                        <input type="checkbox" checked={selectedMagnetFiles.includes(item.index)} onChange={(event) => setSelectedMagnetFiles((current) => event.target.checked ? [...current, item.index] : current.filter((value) => value !== item.index))} />
                        <span className="magnet-file-name" title={item.path}>{item.path}</span>
                        <Text type="secondary" className="magnet-file-size">{item.sizeText || '未知'}</Text>
                      </label>
                    </List.Item>
                  )}
                />
              ) : null}
            </div>
          ) : null}
          <Form.Item name="title" label="视频名"><Input placeholder="默认使用下载文件名，可手动修改" /></Form.Item>
          <Button type="primary" htmlType="submit" disabled={isMagnetDownload && (!magnetFiles.length || !selectedMagnetFiles.length || magnetLoading)}>创建下载任务</Button>
        </Form>
      ),
    },
  ];

  return <PageContainer title="视频" subTitle="视频资源列表；点击详情后预览、编辑并抽帧。" extra={<Space><Button onClick={refresh}>刷新</Button><Button type="primary" onClick={() => setAddOpen(true)}>添加视频</Button></Space>}><ProCard title="视频资源"><ProTable search={false} options={false} toolBarRender={false} size="middle" rowKey="id" className="video-table" tableLayout="fixed" scroll={{ x: 860 }} pagination={false} dataSource={videos} columns={[{ title: '视频', width: 300, render: (_, row) => <Space className="video-row" size={8}><Text className="video-title" strong title={row.title}>{row.title}</Text><Text className="video-name" type="secondary" title={row.name}>{row.name}</Text></Space> }, { title: '来源', dataIndex: 'source', width: 92, ellipsis: true }, { title: '下载', width: 150, render: (_, row) => row.source === '下载' ? <Space direction="vertical" size={0} className="download-cell"><Progress percent={Math.round(row.downloadProgress || 0)} size="small" /><Text type="secondary">{row.downloadSpeed || '-'}</Text></Space> : <Text type="secondary">-</Text> }, { title: '时长', width: 86, render: (_, row) => `${row.duration || 0}s` }, { title: '规格', width: 150, ellipsis: true, render: (_, row) => `${row.resolution || '未知'} / ${row.fps || 0}fps` }, { title: '状态', dataIndex: 'status', width: 96, render: statusTag }, { title: '操作', width: 86, render: (_, row) => <Button size="small" onClick={() => navigate(`/videos/${row.id}`)}>详情</Button> }]} /></ProCard><Modal title="添加视频" open={addOpen} footer={null} onCancel={closeAddVideoModal} destroyOnClose width={680}><Tabs items={addVideoTabs} /></Modal></PageContainer>;
}

function LegacyVideoDetailPage({ datasets, videos, refresh }) {
  const { videoId } = useParams();
  const [extractForm] = Form.useForm();
  const [titleForm] = Form.useForm();
  const [range, setRange] = useState([0, 60]);
  const [interval, setInterval] = useState(5);
  const video = videos.find((item) => item.id === videoId);
  const selectedDatasetId = Form.useWatch('datasetId', extractForm) || datasets[0]?.id;
  const maxDuration = Math.max(0.1, Number(video?.duration) || 60);
  const maxDurationLabel = formatSeconds(maxDuration);
  const safeRange = [Math.min(range[0], maxDuration), Math.min(range[1], maxDuration)];
  const estimatedFrames = Math.max(0, Math.floor((safeRange[1] - safeRange[0]) / interval));

  useEffect(() => { setRange([0, Math.min(60, maxDuration)]); }, [video?.id, maxDuration]);
  useEffect(() => { titleForm.setFieldsValue({ title: video?.title || '' }); }, [titleForm, video?.id, video?.title]);

  async function saveVideoTitle(values) {
    if (!video) return message.warning('视频不存在');
    await api(`/api/videos/${video.id}`, { method: 'PUT', body: JSON.stringify({ title: values.title }) });
    message.success('视频名称已更新');
    refresh();
  }

  async function reprobeVideo() {
    if (!video) return message.warning('视频不存在');
    try {
      const payload = await api(`/api/videos/${video.id}/probe`, { method: 'POST' });
      if (payload.video?.status === '待识别') {
        message.warning(`仍未识别成功：${payload.video.metadataError}`);
      } else {
        message.success('视频元数据已重新识别');
      }
      refresh();
    } catch (error) {
      message.error(`重新识别失败：${error.message}`);
    }
  }

  async function extractFrames() {
    if (!video) return message.warning('视频不存在');
    if (!selectedDatasetId) return message.warning('请先选择目标数据集');
    await api('/api/extractions', { method: 'POST', body: JSON.stringify({ videoId: video.id, datasetId: selectedDatasetId, startSec: safeRange[0], endSec: safeRange[1], intervalSec: interval }) });
    message.success('已创建本地抽帧任务');
    refresh();
  }

  if (!video) return <PageContainer title="视频不存在" onBack={() => window.history.back()}><Alert type="warning" message="请返回视频列表重新选择" /></PageContainer>;
  return <PageContainer title={video.title} subTitle="视频详情、预览、编辑与抽帧。" onBack={() => window.history.back()}><Row gutter={[16, 16]}><Col xs={24} lg={14}><ProCard title="视频预览"><div className="video-preview"><div className="preview-placeholder"><PlayCircleOutlined style={{ fontSize: 42 }} /><Text>{video.title}</Text><Text type="secondary">{video.resolution} / {video.duration}s</Text></div></div><Divider /><Form form={titleForm} layout="vertical" onFinish={saveVideoTitle}><Form.Item name="title" label="视频名" rules={[{ required: true, message: '请输入视频名' }]}><Input placeholder="视频名" /></Form.Item><Button type="primary" htmlType="submit">保存名称</Button></Form><Divider /><Descriptions column={1} size="small" bordered><Descriptions.Item label="来源">{video.source}</Descriptions.Item><Descriptions.Item label="文件名">{video.name}</Descriptions.Item><Descriptions.Item label="存储路径">{video.localPath || '-'}</Descriptions.Item><Descriptions.Item label="下载地址">{video.url || '-'}</Descriptions.Item><Descriptions.Item label="状态">{statusTag(video.status)}</Descriptions.Item></Descriptions><Divider /><Button onClick={reprobeVideo}>重新识别</Button></ProCard></Col><Col xs={24} lg={10}><ProCard title="抽帧"><Form form={extractForm} layout="vertical"><Form.Item name="datasetId" label="抽帧目标数据集" required><Select placeholder="选择数据集" options={datasets.map((item) => ({ value: item.id, label: item.name }))} /></Form.Item><Form.Item label="起止时间"><Slider range min={0} max={maxDuration} value={safeRange} onChange={setRange} tooltip={{ formatter: (value) => `${value}s` }} /></Form.Item><Row gutter={12}><Col span={8}><Form.Item label="起始秒"><InputNumber value={safeRange[0]} min={0} max={maxDuration} onChange={(value) => setRange([value || 0, safeRange[1]])} /></Form.Item></Col><Col span={8}><Form.Item label="结束秒"><InputNumber value={safeRange[1]} min={1} max={maxDuration} onChange={(value) => setRange([safeRange[0], value || 1])} /></Form.Item></Col><Col span={8}><Form.Item label="间隔秒"><InputNumber value={interval} min={0.5} step={0.5} onChange={(value) => setInterval(value || 1)} /></Form.Item></Col></Row><Alert type="info" showIcon message={`预计生成 ${estimatedFrames} 张图片，加入「${datasetName(datasets, selectedDatasetId)}」。`} /><Divider /><Button type="primary" block onClick={extractFrames} disabled={video.status === '下载中'}>启动抽帧</Button></Form></ProCard></Col></Row></PageContainer>;
}

function VideoDetailPage({ datasets, videos, refresh }) {
  const { videoId } = useParams();
  const [extractForm] = Form.useForm();
  const [titleForm] = Form.useForm();
  const videoRef = useRef(null);
  const [range, setRange] = useState([0, 60]);
  const [interval, setInterval] = useState(5);
  const [currentTime, setCurrentTime] = useState(0);
  const [basicEditing, setBasicEditing] = useState(false);
  const video = videos.find((item) => item.id === videoId);
  const selectedDatasetId = Form.useWatch('datasetId', extractForm);
  const maxDuration = Math.max(0.1, Number(video?.duration) || 60);
  const maxDurationLabel = formatSeconds(maxDuration);
  const clipRange = [Math.max(0, Math.min(range[0], maxDuration)), Math.max(0, Math.min(range[1], maxDuration))].sort((left, right) => left - right);
  const estimatedFrames = Math.max(0, Math.floor((clipRange[1] - clipRange[0]) / interval));
  const videoSource = video?.localPath ? `${localApiOrigin}/api/videos/${video.id}/file` : '';
  const resolutionMatch = String(video?.resolution || '').match(/(\d+)x(\d+)/);
  const previewAspectRatio = resolutionMatch ? `${resolutionMatch[1]} / ${resolutionMatch[2]}` : '16 / 9';
  const previewRatio = resolutionMatch ? Number(resolutionMatch[1]) / Number(resolutionMatch[2]) : 16 / 9;
  const previewFitWidth = `${Math.min(100, previewRatio * 62)}vh`;
  const rangeLeft = `${(clipRange[0] / maxDuration) * 100}%`;
  const rangeWidth = `${((clipRange[1] - clipRange[0]) / maxDuration) * 100}%`;
  const playheadTime = Math.max(0, Math.min(currentTime, maxDuration));
  const currentFrame = Math.max(0, Math.round(playheadTime * (Number(video?.fps) || 0)));
  const timelineTicks = Array.from({ length: 11 }, (_, index) => ({ key: index, label: formatSeconds((maxDuration * index) / 10) }));

  useEffect(() => { setRange([0, Math.min(60, maxDuration)]); setCurrentTime(0); }, [video?.id, maxDuration]);
  useEffect(() => { if (video) { titleForm.setFieldsValue({ title: video.title || '' }); setBasicEditing(false); } }, [titleForm, video, video?.id, video?.title]);

  function setClipBoundary(index, value) {
    const nextRange = [...clipRange];
    nextRange[index] = Number(value) || 0;
    setRange(nextRange.sort((left, right) => left - right));
  }

  function setBoundaryFromPlayhead(index) {
    const currentTime = videoRef.current?.currentTime || 0;
    setClipBoundary(index, Math.round(currentTime * 10) / 10);
  }

  function clampTimelineTime(value) {
    const nextTime = Math.max(0, Math.min(Number(value) || 0, maxDuration));
    return nextTime >= maxDuration - 0.05 ? maxDuration : nextTime;
  }

  function seekTo(seconds) {
    const nextTime = clampTimelineTime(seconds);
    setCurrentTime(nextTime);
    if (videoRef.current) videoRef.current.currentTime = nextTime;
  }

  function syncPlayheadFromVideo() {
    setCurrentTime(clampTimelineTime(videoRef.current?.currentTime || 0));
  }

  async function saveVideoTitle(values) {
    if (!video) return message.warning('视频不存在');
    await api(`/api/videos/${video.id}`, { method: 'PUT', body: JSON.stringify({ title: values.title }) });
    message.success('视频名称已更新');
    setBasicEditing(false);
    refresh();
  }

  async function reprobeVideo() {
    if (!video) return message.warning('视频不存在');
    try {
      const payload = await api(`/api/videos/${video.id}/probe`, { method: 'POST' });
      if (payload.video?.status === '待识别') {
        message.warning(`仍未识别成功：${payload.video.metadataError}`);
      } else {
        message.success('视频元数据已重新识别');
      }
      refresh();
    } catch (error) {
      message.error(`重新识别失败：${error.message}`);
    }
  }

  async function extractFrames() {
    if (!video) return message.warning('视频不存在');
    try {
      const values = await extractForm.validateFields(['datasetId']);
      await api('/api/extractions', { method: 'POST', body: JSON.stringify({ videoId: video.id, datasetId: values.datasetId, startSec: clipRange[0], endSec: clipRange[1], intervalSec: interval }) });
      message.success('已创建本地抽帧任务');
      refresh();
    } catch (error) {
      if (error?.errorFields) return;
      message.error(`创建抽帧任务失败：${error.message}`);
    }
  }

  if (!video) return <PageContainer title="视频不存在" onBack={() => window.history.back()}><Alert type="warning" message="请返回视频列表重新选择" /></PageContainer>;
  return (
    <PageContainer title={video.title} subTitle="视频详情、片段首尾与抽帧。" onBack={() => window.history.back()} extra={<Button onClick={reprobeVideo}>重新识别</Button>}>
      <div className="page-stack video-detail-page">
        <ProCard
          title="基础信息"
          extra={basicEditing ? <Space><Button onClick={() => { titleForm.setFieldsValue({ title: video.title }); setBasicEditing(false); }}>取消</Button><Button type="primary" htmlType="submit" form="video-basic-form">保存</Button></Space> : <Button onClick={() => setBasicEditing(true)}>编辑</Button>}
        >
          <Form id="video-basic-form" form={titleForm} onFinish={saveVideoTitle}>
            <Descriptions column={{ xs: 1, md: 2 }} size="small" bordered>
              <Descriptions.Item label="视频名" span={{ xs: 1, md: 2 }}>
                {basicEditing ? <Form.Item name="title" noStyle rules={[{ required: true, message: '请输入视频名' }]}><Input className="basic-title-input" placeholder="视频名" /></Form.Item> : video.title}
              </Descriptions.Item>
              <Descriptions.Item label="状态">{statusTag(video.status)}</Descriptions.Item>
              <Descriptions.Item label="来源">{video.source || '-'}</Descriptions.Item>
              <Descriptions.Item label="文件名">{video.name || '-'}</Descriptions.Item>
              <Descriptions.Item label="规格">{video.resolution || '未知'} / {video.fps || 0}fps</Descriptions.Item>
              <Descriptions.Item label="时长">{video.duration || 0}s</Descriptions.Item>
              <Descriptions.Item label="识别工具">{video.metadataTool || '-'}</Descriptions.Item>
              <Descriptions.Item label="存储路径" span={{ xs: 1, md: 2 }}><Paragraph className="video-info-value" copyable ellipsis={{ rows: 1, tooltip: video.localPath }}>{video.localPath || '-'}</Paragraph></Descriptions.Item>
              <Descriptions.Item label="下载地址" span={{ xs: 1, md: 2 }}><Paragraph className="video-info-value" copyable={Boolean(video.url)} ellipsis={{ rows: 1, tooltip: video.url }}>{video.url || '-'}</Paragraph></Descriptions.Item>
            </Descriptions>
          </Form>
        </ProCard>

        <ProCard title="视频编辑与抽帧" className="video-editor-card">
          <div className="video-editor-layout">
            <div className="video-editor-main">
              <div className="video-preview video-preview-responsive" style={{ '--video-aspect-ratio': previewAspectRatio, '--video-fit-width': previewFitWidth }}>
                {videoSource ? <video ref={videoRef} controls preload="metadata" src={videoSource} onLoadedMetadata={syncPlayheadFromVideo} onTimeUpdate={syncPlayheadFromVideo} onSeeking={syncPlayheadFromVideo} /> : <div className="preview-placeholder"><PlayCircleOutlined style={{ fontSize: 42 }} /><Text>{video.title}</Text><Text type="secondary">视频文件不可用</Text></div>}
              </div>
              <div className="timeline-editor">
                <div className="clip-editor-header">
                  <Text strong>片段范围</Text>
                  <Space size={12} wrap><Text type="secondary">当前 {formatSeconds(playheadTime)}s / 第 {currentFrame} 帧</Text><Text type="secondary">{formatSeconds(clipRange[0])}s - {formatSeconds(clipRange[1])}s / {maxDurationLabel}s</Text></Space>
                </div>
                <div className="timeline-track">
                  <div className="timeline-selected" style={{ left: rangeLeft, width: rangeWidth }} />
                  <div className="timeline-ruler">{timelineTicks.map((tick) => <span key={tick.key}>{tick.label}s</span>)}</div>
                  <Slider className="timeline-playhead-slider" min={0} max={maxDuration} step={0.01} value={playheadTime} onChange={seekTo} tooltip={{ formatter: (value) => `当前 ${formatSeconds(value)}s` }} />
                  <Slider range min={0} max={maxDuration} step={0.01} value={clipRange} onChange={setRange} tooltip={{ formatter: (value) => `${formatSeconds(value)}s` }} />
                </div>
                <div className="timeline-actions">
                  <Button onClick={() => seekTo(clipRange[0])}>跳到起点</Button>
                  <Button onClick={() => setBoundaryFromPlayhead(0)}>当前画面设为起点</Button>
                  <Button onClick={() => setBoundaryFromPlayhead(1)}>当前画面设为终点</Button>
                  <Button onClick={() => seekTo(clipRange[1])}>跳到终点</Button>
                </div>
              </div>
            </div>

            <div className="extract-panel">
              <Form form={extractForm} layout="vertical">
                <Form.Item name="datasetId" label="抽帧目标数据集" rules={[{ required: true, message: '请选择抽帧目标数据集' }]}><Select placeholder="选择数据集" options={datasets.map((item) => ({ value: item.id, label: item.name }))} /></Form.Item>
                <Row gutter={12}>
                  <Col span={12}><Form.Item label="起始秒"><InputNumber className="full-width-input" value={clipRange[0]} min={0} max={maxDuration} step={0.01} precision={2} onChange={(value) => setClipBoundary(0, value)} /></Form.Item></Col>
                  <Col span={12}><Form.Item label="结束秒"><InputNumber className="full-width-input" value={clipRange[1]} min={0.01} max={maxDuration} step={0.01} precision={2} onChange={(value) => setClipBoundary(1, value)} /></Form.Item></Col>
                </Row>
                <Form.Item label="抽帧间隔秒"><InputNumber className="full-width-input" value={interval} min={0.5} step={0.5} onChange={(value) => setInterval(value || 1)} /></Form.Item>
              </Form>
              <Alert type="info" showIcon message={`${estimatedFrames} 张图片`} description={selectedDatasetId ? `加入「${datasetName(datasets, selectedDatasetId)}」` : '请选择目标数据集后再启动抽帧。'} />
              <Button type="primary" block onClick={extractFrames} disabled={video.status === '下载中' || !video.localPath}>启动抽帧</Button>
            </div>
          </div>
        </ProCard>
      </div>
    </PageContainer>
  );
}

function DatasetsPage({ datasets, refresh }) {
  const [form] = Form.useForm();
  const navigate = useNavigate();
  const [createOpen, setCreateOpen] = useState(false);

  async function createDataset(values) {
    await api('/api/datasets', { method: 'POST', body: JSON.stringify(values) });
    message.success('已创建数据集');
    form.resetFields();
    setCreateOpen(false);
    refresh();
  }

  function cancelCreateDataset() {
    form.resetFields();
    setCreateOpen(false);
  }

  return (
    <PageContainer title="数据集" subTitle="从数据集进入图片查看、标注和训练选择。" extra={<Button type="primary" onClick={() => setCreateOpen(true)}>添加新数据集</Button>}>
      <ProCard title="数据集列表" className="dataset-workspace">
        <ProTable
          search={false}
          options={false}
          toolBarRender={false}
          size="middle"
          rowKey="id"
          className="dataset-table"
          tableLayout="fixed"
          scroll={{ x: 920 }}
          pagination={false}
          dataSource={datasets}
          columns={[
            { title: '名称', dataIndex: 'name', width: 220, ellipsis: true, render: (value) => <Text strong title={value}>{value}</Text> },
            { title: '领域', dataIndex: 'domain', width: 110, render: (value) => <Tag>{value || '混合'}</Tag> },
            { title: '触发词', dataIndex: 'trigger', width: 180, ellipsis: true, render: (value) => <Text copyable title={value}>{value}</Text> },
            { title: '图片', width: 96, render: (_, row) => `${row.selectedImages || 0}/${row.totalImages || 0}` },
            { title: '待标注', dataIndex: 'unannotated', width: 90, render: (value) => value || 0 },
            { title: '训练提示', width: 190, render: (_, row) => <Text type="secondary">{estimateTrainingResource(row).hours}</Text> },
            { title: 'Build', dataIndex: 'build', width: 92 },
            { title: '状态', dataIndex: 'status', width: 96, render: statusTag },
            { title: '操作', width: 96, fixed: 'right', render: (_, row) => <Button size="small" onClick={() => navigate(`/datasets/${row.id}`)}>查看图片</Button> },
          ]}
        />
      </ProCard>
      <Modal title="添加新数据集" open={createOpen} onCancel={cancelCreateDataset} destroyOnHidden footer={<Space><Button onClick={cancelCreateDataset}>取消</Button><Button type="primary" htmlType="submit" form="dataset-create-form">创建数据集</Button></Space>} width={620}>
        <Form id="dataset-create-form" form={form} layout="vertical" onFinish={createDataset} initialValues={{ domain: '混合' }}>
          <Form.Item name="name" label="数据集名称" rules={[{ required: true, message: '请输入数据集名称' }]}>
            <Input placeholder="例如 C 视频人物 Dataset" />
          </Form.Item>
          <Row gutter={12}>
            <Col xs={24} md={12}>
              <Form.Item name="domain" label="领域" extra="用于给数据集分类，后续可用于推荐标注规则、训练参数和筛选。">
                <Select options={['人物', '景观', '物品', '载具', '画风', '混合'].map((item) => ({ value: item, label: item }))} />
              </Form.Item>
            </Col>
            <Col xs={24} md={12}>
              <Form.Item name="trigger" label="触发词" extra="训练 LoRA 时绑定的专用提示词；生成图片时输入它来调用这个数据集学到的主体或风格。" rules={[{ pattern: /^[a-zA-Z0-9_\-]+$/, message: '仅支持字母、数字、下划线和连字符' }]}>
                <Input placeholder="例如 my_style_token" />
              </Form.Item>
            </Col>
          </Row>
        </Form>
      </Modal>
    </PageContainer>
  );
}

function DatasetDetailPage({ datasets, refresh }) {
  const { datasetId } = useParams();
  const dataset = datasets.find((item) => item.id === datasetId) || datasets[0];
  const [rows, setRows] = useState([]);
  const [activeImageId, setActiveImageId] = useState();
  const [drawerOpen, setDrawerOpen] = useState(false);
  const [selectedRowKeys, setSelectedRowKeys] = useState([]);
  useEffect(() => { if (dataset?.id) api(`/api/datasets/${dataset.id}/images`).then((payload) => { setRows(payload.images || []); setActiveImageId((payload.images || [])[0]?.id); }).catch((error) => message.error(error.message)); }, [dataset?.id]);
  const activeImage = rows.find((item) => item.id === activeImageId) || rows[0];
  const imageFileUrl = (image) => image && dataset ? `${localApiOrigin}/api/datasets/${dataset.id}/images/${image.id}/file` : '';
  const [screeningLoading, setScreeningLoading] = useState(false);
  const [markingLoading, setMarkingLoading] = useState(false);
  const [annotatingLoading, setAnnotatingLoading] = useState(false);
  const [uploadingImage, setUploadingImage] = useState(false);
  const [captionDrafts, setCaptionDrafts] = useState({});
  const activeCaptionSuggestion = activeImage ? activeImage.llmClassification?.captionSuggestion || activeImage.suggestion || '' : '';
  const activeCaptionDraft = activeImage ? captionDrafts[activeImage.id] ?? (activeImage.caption || activeCaptionSuggestion) : '';
  const tagFilters = Array.from(new Set(rows.flatMap((item) => imageTags(item)))).sort((left, right) => left.localeCompare(right, 'zh-CN')).map((tag) => ({ text: tag, value: tag }));
  const qualityFilters = [{ text: '80-100', value: 'high' }, { text: '60-79', value: 'medium' }, { text: '0-59', value: 'low' }, { text: '未评分', value: 'unscored' }];
  const screeningFilters = [
    { text: '黑屏/接近黑屏', value: 'black_or_near_black' },
    { text: '白屏/闪白', value: 'white_or_flash' },
    { text: '模糊/低信息量', value: 'blurry_motion' },
  ];
  function imageHasLabel(item, label) {
    return (item.localScreening?.labels || []).map(normalizeScreeningLabel).includes(label);
  }
  function allImageIds() {
    return rows.map((item) => item.id).filter(Boolean);
  }
  function actionImageIds() {
    return selectedRowKeys.length ? selectedRowKeys : allImageIds();
  }
  function selectAllImages() {
    setSelectedRowKeys(allImageIds());
  }
  function clearImageSelection() {
    setSelectedRowKeys([]);
  }
  function setActiveCaptionDraft(value) {
    if (!activeImage) return;
    setCaptionDrafts((drafts) => ({ ...drafts, [activeImage.id]: value }));
  }
  async function saveActiveCaption() {
    if (!activeImage) return;
    try {
      const payload = await api(`/api/datasets/${dataset.id}/images/${activeImage.id}`, { method: 'PUT', body: JSON.stringify({ caption: activeCaptionDraft }) });
      setRows(payload.images || []);
      setCaptionDrafts((drafts) => {
        const nextDrafts = { ...drafts };
        delete nextDrafts[activeImage.id];
        return nextDrafts;
      });
      message.success('最终训练描述已保存');
    } catch (error) {
      message.error(`保存标注失败：${error.message}`);
    }
  }
  async function setActiveImageTrainingSelected(selected) {
    if (!activeImage) return;
    try {
      const payload = await api(`/api/datasets/${dataset.id}/images/${activeImage.id}`, { method: 'PUT', body: JSON.stringify({ selected, reason: selected ? '' : '用户手动设置：不参与训练' }) });
      setRows(payload.images || []);
      message.success(selected ? '已设置参与训练' : '已设置不参与训练');
    } catch (error) {
      message.error(`训练选择设置失败：${error.message}`);
    }
  }
  async function chooseDatasetImages() {
    if (!dataset?.id) return;
    const input = document.createElement('input');
    input.type = 'file';
    input.accept = 'image/*';
    input.multiple = true;
    input.onchange = async () => {
      const files = Array.from(input.files || []);
      if (!files.length) return;
      setUploadingImage(true);
      try {
        let payload;
        for (const file of files) {
          payload = await uploadDatasetImage(dataset.id, file);
        }
        if (payload?.images) setRows(payload.images);
        message.success(`已上传 ${files.length} 张图片`);
      } catch (error) {
        message.error(`上传图片失败：${error.message}`);
      } finally {
        setUploadingImage(false);
      }
    };
    input.click();
  }
  async function runLocalScreening() {
    const imageIds = actionImageIds();
    if (!imageIds.length) return message.warning('当前数据集没有图片');
    setScreeningLoading(true);
    try {
      const payload = await api(`/api/datasets/${dataset.id}/images/screen`, { method: 'POST', body: JSON.stringify({ imageIds }) });
      setRows(payload.images || []);
      message.success(`已更新 ${payload.updated || 0} 张图片的本地初筛标记`);
    } catch (error) {
      message.error(`本地初筛失败：${error.message}`);
    } finally {
      setScreeningLoading(false);
    }
  }
  async function markSelectedImages(selected, reason) {
    if (!selectedRowKeys.length) {
      message.warning('请先在表格中选择图片');
      return;
    }
    setMarkingLoading(true);
    try {
      const payload = await api(`/api/datasets/${dataset.id}/images/mark-by-filter`, { method: 'POST', body: JSON.stringify({ imageIds: selectedRowKeys, selected, reason }) });
      setRows(payload.images || []);
      setSelectedRowKeys([]);
      message.success(`已更新 ${payload.updated || 0} 张图片`);
    } catch (error) {
      message.error(`批量设置失败：${error.message}`);
    } finally {
      setMarkingLoading(false);
    }
  }
  async function runAgentAnnotation() {
    const imageIds = actionImageIds();
    if (!imageIds.length) return message.warning('当前数据集没有图片');
    setAnnotatingLoading(true);
    try {
      const payload = await api(`/api/datasets/${dataset.id}/images/annotate`, { method: 'POST', body: JSON.stringify({ imageIds }) });
      setSelectedRowKeys([]);
      message.success(`智能体标注任务已创建：${payload.task?.target || dataset.name}`);
      refresh?.();
    } catch (error) {
      message.error(`智能体标注失败：${error.message}`);
    } finally {
      setAnnotatingLoading(false);
    }
  }
  if (!dataset) return <PageContainer title="数据集不存在"><Alert type="warning" message="请先创建数据集" /></PageContainer>;
  return <PageContainer title={dataset.name} subTitle="当前数据集下的图片、caption 和选择状态。" onBack={() => window.history.back()}><div className="page-stack"><ProCard><Space wrap><Tag color="blue">{dataset.domain}</Tag><Tag>{dataset.trigger}</Tag><Tag color="green">{rows.filter((item) => trainingSelectedValue(item)).length} 张参与训练</Tag><Tag color="orange">{rows.filter((item) => annotationStatusValue(item) !== '已标注').length} 张未标注</Tag><Tag>{selectedRowKeys.length} 张已勾选</Tag></Space></ProCard><div className="dataset-image-layout"><ProCard title="数据集图片"><ProTable search={false} options={false} toolBarRender={() => [<Button key="upload" loading={uploadingImage} onClick={chooseDatasetImages}>上传图片</Button>, <Button key="select-all" disabled={!rows.length || selectedRowKeys.length === rows.length} onClick={selectAllImages}>全选全部</Button>, <Button key="clear-selection" disabled={!selectedRowKeys.length} onClick={clearImageSelection}>清空选择</Button>, <Button key="screen" type="primary" loading={screeningLoading} onClick={runLocalScreening}>本地初筛</Button>, <Button key="annotate" loading={annotatingLoading} onClick={runAgentAnnotation}>智能体标注</Button>, <Button key="include" loading={markingLoading} disabled={!selectedRowKeys.length} onClick={() => markSelectedImages(true, '')}>设置参与训练</Button>, <Button key="reject" danger loading={markingLoading} disabled={!selectedRowKeys.length} onClick={() => markSelectedImages(false, '用户手动设置：不参与训练')}>设置不参与训练</Button>]} rowSelection={{ selectedRowKeys, onChange: setSelectedRowKeys }} rowKey="id" size="middle" className="image-table" tableLayout="fixed" scroll={{ x: 1240 }} pagination={{ pageSize: 20, showSizeChanger: true }} dataSource={rows} locale={{ emptyText: <Alert type="info" showIcon message="该数据集还没有图片" description="先在视频页导入或下载视频并抽帧。" /> }} onRow={(item) => ({ onClick: () => { setActiveImageId(item.id); setDrawerOpen(true); } })} columns={[{ title: '图片', dataIndex: 'id', width: 128, render: (_, item) => <div className="image-table-thumb"><img src={imageFileUrl(item)} alt={`抽帧 ${item.timestampSec ?? ''} 秒`} loading="lazy" /></div> }, { title: '图片 ID', dataIndex: 'id', width: 260, ellipsis: true, render: (value) => <Text strong ellipsis={{ tooltip: value }}>{value}</Text> }, { title: '时间点', dataIndex: 'timestampSec', width: 90, render: (value) => `${value ?? '-'}s` }, { title: '初筛', width: 190, filters: screeningFilters, onFilter: (value, item) => imageHasLabel(item, value), render: (_, item) => { const labels = screeningIssueLabels(item); return labels.length ? <Space wrap size={[0, 4]}>{labels.map((label) => <React.Fragment key={label}>{screeningLabelTag(label)}</React.Fragment>)}</Space> : <Text type="secondary">-</Text>; } }, { title: 'LLM 分类', width: 120, filters: [{ text: '纯场景', value: 'scene' }, { text: '单人', value: 'single_person' }, { text: '多人', value: 'multi_person' }, { text: '物品', value: 'object' }, { text: '文字/图形', value: 'text_or_graphic' }, { text: '待LLM分类', value: 'unknown' }], onFilter: (value, item) => imageCategoryValue(item) === value, render: (_, item) => imageCategoryTag(imageCategoryValue(item)) }, { title: '标签', width: 220, filters: tagFilters, onFilter: (value, item) => imageTags(item).includes(value), render: (_, item) => { const tags = imageTags(item); return tags.length ? <Space wrap size={[0, 4]}>{tags.slice(0, 4).map((tag) => <Tag key={tag}>{tag}</Tag>)}</Space> : <Text type="secondary">-</Text>; } }, { title: '标注', dataIndex: 'annotation', width: 100, filters: [{ text: '未标注', value: '未标注' }, { text: '已标注', value: '已标注' }], onFilter: (value, item) => annotationStatusValue(item) === value, render: (_, item) => statusTag(annotationStatusValue(item)) }, { title: '质量', width: 100, filters: qualityFilters, onFilter: (value, item) => qualityScoreBand(imageQualityScore(item)) === value, render: (_, item) => qualityScoreTag(imageQualityScore(item)) }, { title: '训练选择', dataIndex: 'selected', width: 110, filters: [{ text: '参与训练', value: 'selected' }, { text: '不参与', value: 'rejected' }], onFilter: (value, item) => value === 'selected' ? trainingSelectedValue(item) : !trainingSelectedValue(item), render: (_, item) => trainingSelectedValue(item) ? <Tag color="green">是</Tag> : <Tag color="red">否</Tag> }, { title: '尺寸', width: 100, render: (_, item) => item.width && item.height ? `${item.width}x${item.height}` : '-' }]} /></ProCard><Drawer title="图片详情" open={Boolean(activeImage && drawerOpen)} onClose={() => setDrawerOpen(false)} width="50%" destroyOnHidden><ProCard title="图片标注" extra={activeImage?.captionLocked ? <Tag color="green">caption 已锁定</Tag> : <Tag color="orange">可编辑</Tag>}>{activeImage ? <div className="caption-editor"><div className="detail-preview"><Image src={imageFileUrl(activeImage)} alt={`当前图片 ${activeImage.timestampSec ?? ''} 秒`} preview={{ mask: '查看 / 缩放' }} /></div><Descriptions column={1} size="small" bordered><Descriptions.Item label="时间点">{activeImage.timestampSec ?? '-'}s</Descriptions.Item><Descriptions.Item label="本地初筛">{screeningIssueLabels(activeImage).length ? <Space wrap>{screeningIssueLabels(activeImage).map((label) => <React.Fragment key={label}>{screeningLabelTag(label)}</React.Fragment>)}</Space> : '-'}</Descriptions.Item><Descriptions.Item label="LLM 分类">{imageCategoryTag(imageCategoryValue(activeImage))}</Descriptions.Item><Descriptions.Item label="主体">{metadataText(activeImage.llmClassification?.subject)}</Descriptions.Item><Descriptions.Item label="场景">{metadataText(activeImage.llmClassification?.sceneType)}</Descriptions.Item><Descriptions.Item label="人数">{metadataText(activeImage.llmClassification?.peopleCount)}</Descriptions.Item><Descriptions.Item label="视角">{metadataText(activeImage.llmClassification?.viewAngle || activeImage.view)}</Descriptions.Item><Descriptions.Item label="标签">{metadataText(activeImage.llmClassification?.tags)}</Descriptions.Item><Descriptions.Item label="模型">{metadataText(activeImage.llmClassification?.model)}</Descriptions.Item><Descriptions.Item label="标注时间">{metadataText(activeImage.llmClassification?.runAt)}</Descriptions.Item><Descriptions.Item label="质量">{qualityScoreTag(imageQualityScore(activeImage))}</Descriptions.Item><Descriptions.Item label="标注状态">{statusTag(annotationStatusValue(activeImage))}</Descriptions.Item><Descriptions.Item label="训练选择">{trainingSelectedValue(activeImage) ? '是' : '否'}</Descriptions.Item></Descriptions><Text strong>最终训练描述</Text><TextArea rows={4} value={activeCaptionDraft} onChange={(event) => setActiveCaptionDraft(event.target.value)} /><div className="caption-suggestion"><Text strong>中文训练描述建议</Text><Paragraph>{activeCaptionSuggestion || '尚未生成建议'}</Paragraph></div><Space wrap><Button type="primary" onClick={saveActiveCaption}>保存标注</Button>{trainingSelectedValue(activeImage) ? <Button danger onClick={() => setActiveImageTrainingSelected(false)}>设置不参与训练</Button> : <Button onClick={() => setActiveImageTrainingSelected(true)}>设置参与训练</Button>}</Space></div> : <Alert type="info" showIcon message="请选择图片" />}</ProCard></Drawer></div></div></PageContainer>;
}

function AnnotationPage() {
  const [prompt, setPrompt] = useState('');
  useEffect(() => { api('/api/annotation-prompt').then((payload) => setPrompt(payload.prompt || '')).catch((error) => message.error(error.message)); }, []);
  async function savePrompt() { await api('/api/annotation-prompt', { method: 'PUT', body: JSON.stringify({ prompt }) }); message.success('提示词已保存到本地文件'); }
  return <PageContainer title="标注" subTitle="标注提示词可查看、可手动修改；智能体标注会使用这里保存的内容。"><ProCard title="中文 VLM 标注提示词"><Form layout="vertical"><Form.Item label="标注提示词"><TextArea rows={20} value={prompt} onChange={(event) => setPrompt(event.target.value)} /></Form.Item><Alert type="info" showIcon message="此提示词会作为智能体标注的基础提示词" description="运行标注时，系统会在这里保存的内容后追加当前数据集 trigger、分类枚举和结构化 JSON 输出约束。质量字段使用 0-100 数字评分，由智能体根据图片训练价值判断。" /><Divider /><Button type="primary" onClick={savePrompt}>保存提示词</Button></Form></ProCard></PageContainer>;
}

function TrainingPage({ datasets, refresh }) {
  const [form] = Form.useForm();
  const [submitting, setSubmitting] = useState(false);
  const [selectedDatasetId, setSelectedDatasetId] = useState(preferredTrainingDataset(datasets)?.id);
  useEffect(() => { if (!selectedDatasetId && preferredTrainingDataset(datasets)?.id) setSelectedDatasetId(preferredTrainingDataset(datasets).id); }, [datasets, selectedDatasetId]);
  const dataset = datasets.find((item) => item.id === selectedDatasetId) || preferredTrainingDataset(datasets);
  const estimate = dataset ? estimateTrainingResource(dataset) : null;
  async function submitTraining(values) {
    setSubmitting(true);
    try {
      const payload = await api('/api/training/jobs', { method: 'POST', body: JSON.stringify({ ...values, datasetId: selectedDatasetId }) });
      message.success(`训练准备完成：${payload.lora?.name || 'LoRA'}`);
      refresh?.();
    } catch (error) {
      message.error(`训练准备失败：${error.message}`);
    } finally {
      setSubmitting(false);
    }
  }
  return <PageContainer title="训练" subTitle="准备 Qwen Image LoRA 训练输入，生成可迁移到 GPU VM 的 manifest 和训练配置。"><div className="page-stack"><Steps current={dataset ? 2 : 0} items={[{ title: '选择数据集' }, { title: '检查图片和 caption' }, { title: '生成训练配置' }, { title: '等待 GPU 执行' }]} /><Row gutter={[16, 16]}><Col xs={24} lg={10}><ProCard title="训练输入"><Form form={form} layout="vertical" initialValues={{ baseModel: 'Qwen Image', resolution: 1024, rank: 16, learningRate: '1e-4', batchSize: 1, seed: 42, strength: 0.8 }} onFinish={submitTraining}><Form.Item label="数据集" required><Select value={selectedDatasetId} onChange={setSelectedDatasetId} placeholder="选择数据集" options={datasets.map((item) => ({ value: item.id, label: `${item.name} / ${item.trigger}` }))} /></Form.Item><Form.Item name="name" label="LoRA 名称"><Input placeholder={dataset ? `${dataset.name} LoRA` : 'LoRA 名称'} /></Form.Item><Form.Item name="baseModel" label="基础模型"><Input /></Form.Item><Row gutter={12}><Col span={12}><Form.Item name="resolution" label="分辨率"><InputNumber min={512} max={2048} step={64} style={{ width: '100%' }} /></Form.Item></Col><Col span={12}><Form.Item name="steps" label="训练步数"><InputNumber min={50} max={20000} placeholder={estimate ? String(estimate.steps) : '自动'} style={{ width: '100%' }} /></Form.Item></Col></Row><Row gutter={12}><Col span={12}><Form.Item name="rank" label="LoRA Rank"><InputNumber min={4} max={128} style={{ width: '100%' }} /></Form.Item></Col><Col span={12}><Form.Item name="batchSize" label="Batch"><InputNumber min={1} max={16} style={{ width: '100%' }} /></Form.Item></Col></Row><Row gutter={12}><Col span={12}><Form.Item name="learningRate" label="学习率"><Input /></Form.Item></Col><Col span={12}><Form.Item name="seed" label="Seed"><InputNumber min={0} style={{ width: '100%' }} /></Form.Item></Col></Row><Form.Item name="gpuCommand" label="GPU VM 执行命令"><TextArea rows={3} placeholder="部署 GPU VM 后填入 musubi-tuner / Qwen Image 训练命令" /></Form.Item><Button type="primary" block htmlType="submit" loading={submitting} disabled={!dataset}>准备训练任务</Button></Form></ProCard></Col><Col xs={24} lg={14}><div className="page-stack">{dataset ? <TrainingResourceHint dataset={dataset} /> : <Alert type="warning" showIcon message="请先创建数据集" />}<ProCard title="就绪检查"><Descriptions column={1} bordered size="small"><Descriptions.Item label="数据集">{dataset?.name || '-'}</Descriptions.Item><Descriptions.Item label="触发词">{dataset?.trigger || '-'}</Descriptions.Item><Descriptions.Item label="参与训练图片">{dataset?.selectedImages ?? 0} / {dataset?.totalImages ?? 0}</Descriptions.Item><Descriptions.Item label="已确认 caption">{dataset?.captionLocked ?? 0}</Descriptions.Item><Descriptions.Item label="未标注">{dataset?.unannotated ?? 0}</Descriptions.Item><Descriptions.Item label="输出">local-data/training-runs/&lt;run_id&gt;/train_config.json</Descriptions.Item></Descriptions><Divider /><Alert type="info" showIcon message="当前会完成训练前准备" description="本地会持久化 LoRA 版本、训练 manifest 和配置文件；GPU VM 部署后，可读取这些文件执行真实训练并回填权重路径。" /></ProCard></div></Col></Row></div></PageContainer>;
}

function LorasPage({ datasets, loras: loraRows, refresh }) {
  const [editForm] = Form.useForm();
  const [editing, setEditing] = useState();
  const [saving, setSaving] = useState(false);
  function openEdit(row) { setEditing(row); editForm.setFieldsValue(row); }
  async function saveEdit() {
    setSaving(true);
    try {
      const values = await editForm.validateFields();
      await api(`/api/loras/${editing.id}`, { method: 'PUT', body: JSON.stringify(values) });
      message.success('LoRA 已更新');
      setEditing(undefined);
      refresh?.();
    } catch (error) {
      message.error(`保存失败：${error.message}`);
    } finally {
      setSaving(false);
    }
  }
  return <PageContainer title="LoRA 版本" subTitle="管理训练准备完成、等待 GPU 训练或已经可用的 LoRA 版本。"><ProCard extra={<Button onClick={refresh}>刷新</Button>}><ProTable search={false} options={false} toolBarRender={false} size="middle" rowKey="id" tableLayout="fixed" scroll={{ x: 1120 }} pagination={{ pageSize: 12 }} dataSource={loraRows} locale={{ emptyText: <Alert type="info" showIcon message="还没有 LoRA 版本" description="先到训练页准备一个训练任务。" /> }} columns={[{ title: 'LoRA', dataIndex: 'name', width: 220, render: (value, row) => <Space direction="vertical" size={0}><Text strong>{value}</Text><Text type="secondary">{row.trigger}</Text></Space> }, { title: '数据集', dataIndex: 'datasetId', width: 180, render: (value) => datasetName(datasets, value) }, { title: '基础模型', dataIndex: 'baseModel', width: 140 }, { title: '图片', dataIndex: 'imageCount', width: 80 }, { title: '推荐权重', dataIndex: 'strength', width: 100 }, { title: '状态', dataIndex: 'status', width: 130, render: statusTag }, { title: '权重路径', dataIndex: 'weightPath', ellipsis: true, render: (value) => value || <Text type="secondary">待 GPU 回填</Text> }, { title: '操作', width: 90, render: (_, row) => <Button size="small" onClick={() => openEdit(row)}>编辑</Button> }]} /></ProCard><Modal title="编辑 LoRA" open={Boolean(editing)} onCancel={() => setEditing(undefined)} onOk={saveEdit} confirmLoading={saving} destroyOnClose><Form form={editForm} layout="vertical"><Form.Item name="name" label="名称" rules={[{ required: true, message: '请输入名称' }]}><Input /></Form.Item><Form.Item name="status" label="状态"><Select options={['等待GPU训练', '训练中', '可用', '失败', '归档'].map((value) => ({ value, label: value }))} /></Form.Item><Form.Item name="strength" label="推荐权重"><InputNumber min={0} max={2} step={0.05} style={{ width: '100%' }} /></Form.Item><Form.Item name="weightPath" label="权重路径"><Input placeholder="GPU VM 训练完成后的 safetensors 路径" /></Form.Item><Form.Item name="notes" label="备注"><TextArea rows={3} /></Form.Item></Form></Modal></PageContainer>;
}

function EvaluationPage({ loras: loraRows, evaluations, refresh }) {
  const [form] = Form.useForm();
  const [submitting, setSubmitting] = useState(false);
  const [uploadingResult, setUploadingResult] = useState('');
  async function submitEvaluation(values) {
    setSubmitting(true);
    try {
      await api('/api/evaluations', { method: 'POST', body: JSON.stringify(values) });
      message.success('测试生成请求已准备，等待 GPU 执行');
      form.resetFields(['seed']);
      refresh?.();
    } catch (error) {
      message.error(`创建失败：${error.message}`);
    } finally {
      setSubmitting(false);
    }
  }
  function chooseResultImage(evaluationId, resultId) {
    const input = document.createElement('input');
    input.type = 'file';
    input.accept = 'image/png,image/jpeg,image/webp';
    input.onchange = async () => {
      const file = input.files?.[0];
      if (!file) return;
      setUploadingResult(`${evaluationId}:${resultId}`);
      try {
        await uploadEvaluationResult(evaluationId, resultId, file);
        message.success('生成结果已导入');
        refresh?.();
      } catch (error) {
        message.error(`导入失败：${error.message}`);
      } finally {
        setUploadingResult('');
      }
    };
    input.click();
  }
  async function markResult(evaluationId, resultId, status) {
    try {
      await api(`/api/evaluations/${evaluationId}/results/${resultId}`, { method: 'PUT', body: JSON.stringify({ status }) });
      message.success('结果状态已更新');
      refresh?.();
    } catch (error) {
      message.error(`更新失败：${error.message}`);
    }
  }
  const availableLoras = loraRows.filter((item) => item.status !== '归档');
  return <PageContainer title="测试生成" subTitle="配置 LoRA 测试 prompt，保存请求并回填 GPU 生成结果。"><Row gutter={[16, 16]}><Col xs={24} lg={9}><ProCard title="生成配置"><Form form={form} layout="vertical" initialValues={{ loraId: availableLoras[0]?.id, prompt: `${availableLoras[0]?.trigger || 'custom_trigger_token'}，清晰构图，正面视角，柔和光线`, negativePrompt: '低清晰度，严重模糊，文字水印，变形', seed: 42, count: 2, width: 1024, height: 1024, steps: 30, guidanceScale: 4 }} onFinish={submitEvaluation}><Form.Item name="loraId" label="LoRA"><Select allowClear placeholder="可选择基础模型" options={availableLoras.map((item) => ({ value: item.id, label: `${item.name} / ${item.status}` }))} /></Form.Item><Form.Item name="prompt" label="Prompt" rules={[{ required: true, message: '请输入 Prompt' }]}><TextArea rows={5} /></Form.Item><Form.Item name="negativePrompt" label="Negative Prompt"><TextArea rows={3} /></Form.Item><Row gutter={12}><Col span={12}><Form.Item name="seed" label="Seed"><InputNumber min={0} style={{ width: '100%' }} /></Form.Item></Col><Col span={12}><Form.Item name="count" label="数量"><InputNumber min={1} max={8} style={{ width: '100%' }} /></Form.Item></Col></Row><Row gutter={12}><Col span={12}><Form.Item name="width" label="宽"><InputNumber min={512} max={2048} step={64} style={{ width: '100%' }} /></Form.Item></Col><Col span={12}><Form.Item name="height" label="高"><InputNumber min={512} max={2048} step={64} style={{ width: '100%' }} /></Form.Item></Col></Row><Row gutter={12}><Col span={12}><Form.Item name="steps" label="Steps"><InputNumber min={1} max={100} style={{ width: '100%' }} /></Form.Item></Col><Col span={12}><Form.Item name="guidanceScale" label="CFG"><InputNumber min={0} max={20} step={0.5} style={{ width: '100%' }} /></Form.Item></Col></Row><Button type="primary" block htmlType="submit" loading={submitting}>准备测试生成</Button></Form><Divider /><Alert type="info" showIcon message="GPU 回填方式" description="GPU VM 可调用结果导入接口，或在页面里手动导入生成图片；导入后这里会显示真实图片。" /></ProCard></Col><Col xs={24} lg={15}><ProCard title="生成请求" extra={<Button onClick={refresh}>刷新</Button>}>{evaluations.length ? <div className="page-stack">{evaluations.map((item) => <div className="evaluation-run" key={item.id}><Space wrap><Text strong>{item.loraName}</Text>{statusTag(item.status)}<Tag>seed {item.seed}</Tag><Tag>{item.width}x{item.height}</Tag><Text type="secondary">{item.runId}</Text></Space><Paragraph ellipsis={{ rows: 2, expandable: true }}>{item.prompt}</Paragraph><div className="generated-grid">{(item.results || []).map((result) => <div className="generated-card" key={result.id}>{result.imageUrl ? <img className="generated-image" src={evaluationResultImageUrl(result)} alt={`seed ${result.seed}`} /> : <div className="generated-preview">{result.status || item.status}</div>}<div className="generated-meta"><Space direction="vertical" size={6} style={{ width: '100%' }}><Space wrap><Text>seed {result.seed}</Text>{statusTag(result.status || item.status)}</Space>{result.error ? <Text type="danger">{result.error}</Text> : null}<Space wrap><Button size="small" loading={uploadingResult === `${item.id}:${result.id}`} onClick={() => chooseResultImage(item.id, result.id)}>导入结果</Button><Button size="small" onClick={() => markResult(item.id, result.id, '失败')}>标记失败</Button></Space></Space></div></div>)}</div></div>)}</div> : <Alert type="info" showIcon message="还没有生成请求" description="准备请求后，GPU VM 可读取 local-data/evaluation-runs 下的 generation_request.json 执行生成。" />}</ProCard></Col></Row></PageContainer>;
}
function ModelsPage() {
  const [status, setStatus] = useState();
  const [loading, setLoading] = useState(false);
  const [checking, setChecking] = useState('');
  async function loadStatus() {
    setLoading(true);
    try {
      const payload = await api('/api/models/status');
      setStatus(payload);
    } catch (error) {
      message.error(`读取模型状态失败：${error.message}`);
    } finally {
      setLoading(false);
    }
  }
  useEffect(() => { loadStatus(); }, []);
  async function checkAsset(assetId) {
    setChecking(assetId);
    try {
      const payload = await api(`/api/models/checks/${assetId}`);
      message.success(`${payload.check?.name || payload.check?.id || assetId}：${payload.check?.status || '完成'}`);
      loadStatus();
    } catch (error) {
      message.error(`检查失败：${error.message}`);
    } finally {
      setChecking('');
    }
  }
  const assets = status?.assets || [];
  const gpu = status?.gpu || {};
  const docker = status?.docker || {};
  const summary = status?.summary || {};
  return <PageContainer title="模型 / GPU" subTitle="检查本地 GPU、vLLM 镜像、Qwen Image 模型资产和训练工具状态。"><Row gutter={[16, 16]}><Col xs={24} lg={15}><ProCard title="模型与工具" extra={<Button loading={loading} onClick={loadStatus}>刷新</Button>}><List loading={loading} dataSource={assets} renderItem={(item) => <List.Item actions={[<Button key="check" loading={checking === item.id} onClick={() => checkAsset(item.id)}>检查</Button>]}><List.Item.Meta title={<Space wrap><Text strong>{item.name}</Text>{statusTag(item.status)}{item.required ? <Tag>必需</Tag> : null}</Space>} description={<Space direction="vertical" size={2}><Text>{item.path}</Text><Text type="secondary">{item.fileCount || 0} 个文件 / {item.size || '0 B'} / {item.kind}</Text></Space>} /></List.Item>} /></ProCard></Col><Col xs={24} lg={9}><div className="page-stack"><ProCard title="GPU"><Descriptions column={1} bordered size="small"><Descriptions.Item label="状态">{statusTag(gpu.status || '未知')}</Descriptions.Item>{(gpu.gpus || []).map((item, index) => <React.Fragment key={`${item.name}-${index}`}><Descriptions.Item label={`GPU ${index}`}>{item.name}</Descriptions.Item><Descriptions.Item label="显存">{item.memoryUsedMb} / {item.memoryTotalMb} MB</Descriptions.Item><Descriptions.Item label="驱动">{item.driverVersion}</Descriptions.Item><Descriptions.Item label="温度 / 利用率">{item.temperatureC} C / {item.utilizationPct}%</Descriptions.Item></React.Fragment>)}{gpu.message ? <Descriptions.Item label="信息">{gpu.message}</Descriptions.Item> : null}</Descriptions><Divider /><Button loading={checking === 'gpu'} onClick={() => checkAsset('gpu')}>检查 GPU</Button></ProCard><ProCard title="vLLM / Docker"><Descriptions column={1} bordered size="small"><Descriptions.Item label="Docker">{statusTag(docker.status || '未知')}</Descriptions.Item><Descriptions.Item label="版本">{docker.version || '-'}</Descriptions.Item><Descriptions.Item label="vLLM 镜像">{docker.vllmImage || '-'}</Descriptions.Item><Descriptions.Item label="镜像状态">{docker.imagePresent ? <Tag color="green">已拉取</Tag> : <Tag color="orange">未发现</Tag>}</Descriptions.Item><Descriptions.Item label="整体就绪">{summary.allReady ? <Tag color="green">是</Tag> : <Tag color="orange">否</Tag>}</Descriptions.Item></Descriptions><Divider /><Button loading={checking === 'vllm'} onClick={() => checkAsset('vllm')}>检查 vLLM</Button></ProCard></div></Col></Row></PageContainer>;
}
function TasksPage({ tasks, refresh }) {
  const terminalStatuses = new Set(['完成', '失败', '已取消']);
  async function cancel(row) {
    if (!window.confirm(`取消任务「${row.type}」？`)) return;
    await api(`/api/tasks/${row.id}/cancel`, { method: 'POST' });
    message.success('已请求取消任务');
    refresh();
  }
  return <PageContainer title="任务" subTitle="下载、抽帧、标注、训练和测试生成任务。"><ProCard extra={<Button onClick={refresh}>刷新</Button>}><ProTable search={false} options={false} toolBarRender={false} size="middle" rowKey="id" pagination={false} dataSource={tasks} columns={[{ title: '任务', dataIndex: 'type' }, { title: '目标', dataIndex: 'target' }, { title: '状态', dataIndex: 'status', render: statusTag }, { title: '进度', dataIndex: 'progress', render: (value) => <Progress percent={value || 0} size="small" /> }, { title: '操作', render: (_, row) => !terminalStatuses.has(row.status) ? <Button danger onClick={() => cancel(row)}>取消</Button> : <Text type="secondary">-</Text> }]} /></ProCard></PageContainer>;
}

function AppRoutes({ data }) {
  return <Routes><Route path="/" element={<Navigate to="/dashboard" replace />} /><Route path="/dashboard" element={<DashboardPage datasets={data.datasets} tasks={data.tasks} loras={data.loras} apiError={data.error} />} /><Route path="/videos" element={<VideosPage datasets={data.datasets} videos={data.videos} refresh={data.refresh} />} /><Route path="/videos/:videoId" element={<VideoDetailPage datasets={data.datasets} videos={data.videos} refresh={data.refresh} />} /><Route path="/datasets" element={<DatasetsPage datasets={data.datasets} refresh={data.refresh} />} /><Route path="/datasets/:datasetId" element={<DatasetDetailPage datasets={data.datasets} refresh={data.refresh} />} /><Route path="/annotation" element={<AnnotationPage />} /><Route path="/training" element={<TrainingPage datasets={data.datasets} refresh={data.refresh} />} /><Route path="/loras" element={<LorasPage datasets={data.datasets} loras={data.loras} refresh={data.refresh} />} /><Route path="/evaluation" element={<EvaluationPage loras={data.loras} evaluations={data.evaluations} refresh={data.refresh} />} /><Route path="/models" element={<ModelsPage />} /><Route path="/tasks" element={<TasksPage tasks={data.tasks} refresh={data.refresh} />} /><Route path="*" element={<Navigate to="/dashboard" replace />} /></Routes>;
}

export default function App() {
  const location = useLocation();
  const navigate = useNavigate();
  const data = useLocalData();
  return <ProLayout className="app-layout" title="Qwen Image LoRA" logo={false} route={route} location={location} layout="mix" fixedHeader siderWidth={232} menuItemRender={(item, dom) => <a onClick={() => navigate(item.path || '/dashboard')}>{dom}</a>} token={{ header: { colorBgHeader: '#ffffff' }, sider: { colorMenuBackground: '#ffffff' } }}><AppRoutes data={data} /></ProLayout>;
}












