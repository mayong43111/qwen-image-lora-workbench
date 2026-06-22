[CmdletBinding(SupportsShouldProcess)]
param(
  [string]$SubscriptionId,
  [string]$ResourceGroup = "rg-qwen-lora-neu",
  [string]$Location = "northeurope",
  [string]$VmName = "vm-qwen-lora-a100",
  [string]$VmSize = "Standard_NC24ads_A100_v4",
  [string]$AdminUsername = "azureuser",
  [string]$SshPublicKeyPath = "$HOME/.ssh/id_rsa.pub",
  [string]$ImageResourceGroup = "RG-AI-IMAGE-NORTHEUROPE",
  [string]$Layer2ImageName = "ai-a100-layer2-orchestrator-ubuntu2204-202606201236",
  [string]$ImageId,
  [int]$OsDiskSizeGb = 512,
  [string]$VnetName,
  [string]$SubnetName = "default",
  [string]$NsgName,
  [string]$PublicIpName,
  [string]$NicName,
  [string]$WorkbenchRepo = "https://github.com/mayong43111/qwen-image-lora-workbench.git",
  [string]$WorkbenchBranch = "main",
  [string]$VllmImage = "docker.io/vllm/vllm-openai:v0.23.0",
  [string]$QwenImageDitRepo = "Qwen/Qwen-Image",
  [string]$QwenImageVaeRepo = "Qwen/Qwen-Image",
  [string]$QwenImageTextEncoderRepo = "Qwen/Qwen-Image",
  [string]$QwenVlRepo = "Qwen/Qwen2.5-VL-7B-Instruct",
  [string]$MusubiTunerRepo = "https://github.com/kohya-ss/musubi-tuner.git",
  [string]$HuggingFaceToken = "",
  [switch]$OpenPublicPorts = $true
)

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

function Require-Command($Name) {
  if (-not (Get-Command $Name -ErrorAction SilentlyContinue)) {
    throw "Required command not found: $Name"
  }
}

function AzJson([string[]]$Arguments) {
  $output = & az @Arguments -o json
  if ($LASTEXITCODE -ne 0) { throw "az $($Arguments -join ' ') failed" }
  if (-not $output) { return $null }
  return $output | ConvertFrom-Json
}

Require-Command az

if ($SubscriptionId) {
  az account set --subscription $SubscriptionId | Out-Null
}

if (-not (Test-Path $SshPublicKeyPath)) {
  throw "SSH public key not found: $SshPublicKeyPath"
}

$VnetName = if ($VnetName) { $VnetName } else { "$VmName-vnet" }
$NsgName = if ($NsgName) { $NsgName } else { "$VmName-nsg" }
$PublicIpName = if ($PublicIpName) { $PublicIpName } else { "$VmName-pip" }
$NicName = if ($NicName) { $NicName } else { "$VmName-nic" }

if (-not $ImageId) {
  $image = AzJson @("image", "show", "--resource-group", $ImageResourceGroup, "--name", $Layer2ImageName)
  if (-not $image.id) { throw "Layer2 image not found: $ImageResourceGroup/$Layer2ImageName" }
  if ($image.location -ne $Location) {
    throw "Managed image '$Layer2ImageName' is in '$($image.location)', but VM location is '$Location'. Replicate the image to $Location or pass a same-region Shared Image Gallery version id through -ImageId."
  }
  $ImageId = $image.id
}

$cloudInit = @"
#cloud-config
package_update: true
package_upgrade: false
write_files:
  - path: /opt/qwen-image-lora-workbench/bootstrap-gpu-workbench.sh
    permissions: '0755'
    owner: root:root
    content: |
      #!/usr/bin/env bash
      set -euxo pipefail
      export DEBIAN_FRONTEND=noninteractive
      export HF_HUB_ENABLE_HF_TRANSFER=1
      export HF_HOME=/data/huggingface
      export HF_TOKEN='$HuggingFaceToken'
      WORKBENCH_REPO='$WorkbenchRepo'
      WORKBENCH_BRANCH='$WorkbenchBranch'
      VLLM_IMAGE='$VllmImage'
      QWEN_IMAGE_DIT_REPO='$QwenImageDitRepo'
      QWEN_IMAGE_VAE_REPO='$QwenImageVaeRepo'
      QWEN_IMAGE_TEXT_ENCODER_REPO='$QwenImageTextEncoderRepo'
      QWEN_VL_REPO='$QwenVlRepo'
      MUSUBI_TUNER_REPO='$MusubiTunerRepo'

      mkdir -p /data/models /data/huggingface /opt/qwen-image-lora-workbench /var/log/qwen-image-lora-workbench
      apt-get update
      apt-get install -y ca-certificates curl git git-lfs jq unzip ffmpeg aria2 python3 python3-venv python3-pip build-essential ninja-build
      git lfs install --system

      if ! command -v node >/dev/null 2>&1 || ! node --version | grep -Eq '^v2[2-9]\.'; then
        curl -fsSL https://deb.nodesource.com/setup_22.x | bash -
        apt-get install -y nodejs
      fi

      if ! command -v docker >/dev/null 2>&1; then
        apt-get install -y docker.io
        systemctl enable --now docker
      else
        systemctl enable --now docker || true
      fi
      usermod -aG docker '$AdminUsername' || true
      docker pull "`${VLLM_IMAGE}"

      python3 -m pip install --upgrade pip
      python3 -m pip install --upgrade 'huggingface_hub[cli]' hf_transfer

      download_model() {
        local repo="`$1"
        local target="`$2"
        mkdir -p "`$target"
        if [ -n "`${HF_TOKEN}" ]; then
          huggingface-cli download "`$repo" --local-dir "`$target" --token "`$HF_TOKEN"
        else
          huggingface-cli download "`$repo" --local-dir "`$target"
        fi
      }

      download_model "`$QWEN_IMAGE_DIT_REPO" /data/models/qwen-image-2512-dit
      download_model "`$QWEN_IMAGE_VAE_REPO" /data/models/qwen-image-vae
      download_model "`$QWEN_IMAGE_TEXT_ENCODER_REPO" /data/models/qwen-image-text-encoder
      download_model "`$QWEN_VL_REPO" /data/models/qwen2.5-vl-7b-instruct

      if [ ! -d /opt/musubi-tuner/.git ]; then
        git clone "`$MUSUBI_TUNER_REPO" /opt/musubi-tuner
      fi
      python3 -m venv /opt/musubi-tuner/.venv
      /opt/musubi-tuner/.venv/bin/python -m pip install --upgrade pip
      if [ -f /opt/musubi-tuner/requirements.txt ]; then
        /opt/musubi-tuner/.venv/bin/pip install -r /opt/musubi-tuner/requirements.txt
      fi
      if [ -f /opt/musubi-tuner/setup.py ] || [ -f /opt/musubi-tuner/pyproject.toml ]; then
        /opt/musubi-tuner/.venv/bin/pip install -e /opt/musubi-tuner
      fi

      if [ ! -d /opt/qwen-image-lora-workbench/app/.git ]; then
        git clone --branch "`$WORKBENCH_BRANCH" "`$WORKBENCH_REPO" /opt/qwen-image-lora-workbench/app
      else
        git -C /opt/qwen-image-lora-workbench/app fetch origin "`$WORKBENCH_BRANCH"
        git -C /opt/qwen-image-lora-workbench/app checkout "`$WORKBENCH_BRANCH"
        git -C /opt/qwen-image-lora-workbench/app pull --ff-only
      fi
      cd /opt/qwen-image-lora-workbench/app
      npm ci
      npm run build
      python3 -m venv .venv
      .venv/bin/python -m pip install --upgrade pip
      .venv/bin/pip install -r requirements.txt
      chown -R '$AdminUsername':'$AdminUsername' /opt/qwen-image-lora-workbench /data/models /data/huggingface /opt/musubi-tuner

      cat >/etc/systemd/system/qwen-lora-api.service <<'SERVICE'
      [Unit]
      Description=Qwen Image LoRA Workbench API
      After=network-online.target
      Wants=network-online.target

      [Service]
      Type=simple
      WorkingDirectory=/opt/qwen-image-lora-workbench/app
      Environment=PATH=/opt/qwen-image-lora-workbench/app/.venv/bin:/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin
      ExecStart=/opt/qwen-image-lora-workbench/app/.venv/bin/python -m uvicorn server.app.main:app --host 0.0.0.0 --port 8787
      Restart=always
      RestartSec=5
      User=$AdminUsername
      Group=$AdminUsername

      [Install]
      WantedBy=multi-user.target
      SERVICE

      cat >/etc/systemd/system/qwen-lora-web.service <<'SERVICE'
      [Unit]
      Description=Qwen Image LoRA Workbench Web
      After=network-online.target qwen-lora-api.service
      Wants=network-online.target

      [Service]
      Type=simple
      WorkingDirectory=/opt/qwen-image-lora-workbench/app
      ExecStart=/usr/bin/npx vite preview --host 0.0.0.0 --port 5174
      Restart=always
      RestartSec=5
      User=$AdminUsername
      Group=$AdminUsername

      [Install]
      WantedBy=multi-user.target
      SERVICE

      systemctl daemon-reload
      systemctl enable --now qwen-lora-api.service qwen-lora-web.service
      nvidia-smi || true
      docker image inspect "`$VLLM_IMAGE" >/dev/null
runcmd:
  - [bash, /opt/qwen-image-lora-workbench/bootstrap-gpu-workbench.sh]
"@

$tempCloudInit = Join-Path ([IO.Path]::GetTempPath()) "$VmName-cloud-init.yaml"
Set-Content -Path $tempCloudInit -Value $cloudInit -Encoding utf8

$deploymentApplied = $false
if ($PSCmdlet.ShouldProcess($VmName, "create resource group, networking, and Spot A100 VM in $Location")) {
  az group create --name $ResourceGroup --location $Location | Out-Null
  az network nsg create --resource-group $ResourceGroup --location $Location --name $NsgName | Out-Null
  az network nsg rule create --resource-group $ResourceGroup --nsg-name $NsgName --name AllowSSH --priority 1000 --access Allow --direction Inbound --protocol Tcp --source-address-prefixes Internet --source-port-ranges '*' --destination-address-prefixes '*' --destination-port-ranges 22 | Out-Null
  if ($OpenPublicPorts) {
    az network nsg rule create --resource-group $ResourceGroup --nsg-name $NsgName --name AllowWorkbenchWeb --priority 1010 --access Allow --direction Inbound --protocol Tcp --source-address-prefixes Internet --source-port-ranges '*' --destination-address-prefixes '*' --destination-port-ranges 5174 | Out-Null
    az network nsg rule create --resource-group $ResourceGroup --nsg-name $NsgName --name AllowWorkbenchApi --priority 1020 --access Allow --direction Inbound --protocol Tcp --source-address-prefixes Internet --source-port-ranges '*' --destination-address-prefixes '*' --destination-port-ranges 8787 | Out-Null
  }
  az network vnet create --resource-group $ResourceGroup --location $Location --name $VnetName --address-prefixes 10.61.0.0/16 --subnet-name $SubnetName --subnet-prefixes 10.61.1.0/24 | Out-Null
  az network public-ip create --resource-group $ResourceGroup --location $Location --name $PublicIpName --sku Standard --allocation-method Static | Out-Null
  az network nic create --resource-group $ResourceGroup --location $Location --name $NicName --vnet-name $VnetName --subnet $SubnetName --network-security-group $NsgName --public-ip-address $PublicIpName | Out-Null
  az vm create `
    --resource-group $ResourceGroup `
    --location $Location `
    --name $VmName `
    --nics $NicName `
    --image $ImageId `
    --size $VmSize `
    --admin-username $AdminUsername `
    --ssh-key-values $SshPublicKeyPath `
    --priority Spot `
    --eviction-policy Deallocate `
    --max-price -1 `
    --os-disk-size-gb $OsDiskSizeGb `
    --custom-data $tempCloudInit | Out-Null
  $deploymentApplied = $true
}

$ipAddress = $null
if ($deploymentApplied) {
  $publicIp = AzJson @("network", "public-ip", "show", "--resource-group", $ResourceGroup, "--name", $PublicIpName, "--query", "{ip:ipAddress}")
  $ipAddress = $publicIp.ip
}

$ssh = $null
$web = $null
$api = $null
if ($ipAddress) {
  $ssh = "ssh $AdminUsername@$ipAddress"
  $web = "http://$ipAddress:5174"
  $api = "http://$ipAddress:8787"
}

[pscustomobject]@{
  ResourceGroup = $ResourceGroup
  VmName = $VmName
  Location = $Location
  VmSize = $VmSize
  Priority = "Spot"
  ImageId = $ImageId
  PublicIp = $ipAddress
  Ssh = $ssh
  Web = $web
  Api = $api
  CloudInit = $tempCloudInit
} | ConvertTo-Json -Depth 5
