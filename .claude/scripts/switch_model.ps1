param(
    [string]$ModelAlias = ""
)

$ErrorActionPreference = "Stop"
$settingsPath = "$env:USERPROFILE\.claude\settings.json"
$scriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$projectDir = Resolve-Path "$scriptDir\..\.."
$configPyPath = Join-Path $projectDir "managed_agents\config.py"
$adapterPyPath = Join-Path $projectDir "managed_agents\api\adapter.py"

$modelMap = @{
    "pro"      = "deepseek-v4-pro"
    "flash"    = "deepseek-v4-flash"
    "v4-pro"   = "deepseek-v4-pro"
    "v4-flash" = "deepseek-v4-flash"
    "chat"     = "deepseek-chat"
    "reasoner" = "deepseek-reasoner"
}

$modelCapabilities = @{
    "deepseek-v4-pro"   = @{ max_tokens=4096; vision=$false; tools=$true; stream=$false }
    "deepseek-v4-flash" = @{ max_tokens=4096; vision=$false; tools=$true; stream=$false }
    "deepseek-chat"     = @{ max_tokens=4096; vision=$false; tools=$true; stream=$false }
    "deepseek-reasoner" = @{ max_tokens=4096; vision=$false; tools=$true; stream=$false }
}

# ---------- 无参：显示当前模型 ----------
if (-not $ModelAlias) {
    if (-not (Test-Path $settingsPath)) {
        Write-Host "ERROR: settings.json not found at $settingsPath" -ForegroundColor Red
        exit 1
    }
    $settings = Get-Content $settingsPath -Raw -Encoding UTF8 | ConvertFrom-Json
    $current = $settings.env.ANTHROPIC_MODEL
    Write-Host "Current model: $current" -ForegroundColor Cyan
    Write-Host ""
    foreach ($alias in ($modelMap.Keys | Sort-Object)) {
        $full = $modelMap[$alias]
        $marker = if ($full -eq $current) { " [active]" } else { "" }
        Write-Host "  $alias -> $full$marker"
    }
    Write-Host ""
    Write-Host "Usage: switch_model.ps1 -ModelAlias <alias>"
    exit 0
}

# ---------- 解析别名 ----------
$targetModel = if ($modelMap.ContainsKey($ModelAlias)) {
    $modelMap[$ModelAlias]
} elseif ($modelMap.Values -contains $ModelAlias) {
    $ModelAlias
} else {
    Write-Host "Unknown model: $ModelAlias" -ForegroundColor Red
    Write-Host "Available: $($modelMap.Keys -join ', ')" -ForegroundColor Yellow
    exit 1
}

# ---------- 更新 settings.json ----------
if (-not (Test-Path $settingsPath)) {
    Write-Host "ERROR: settings.json not found" -ForegroundColor Red
    exit 1
}

$settings = Get-Content $settingsPath -Raw -Encoding UTF8 | ConvertFrom-Json
$oldModel = $settings.env.ANTHROPIC_MODEL

if ($oldModel -eq $targetModel) {
    Write-Host "Already using $targetModel, no change needed." -ForegroundColor Green
    exit 0
}

if ($ModelAlias -eq "pro" -or $ModelAlias -eq "v4-pro") {
    $settings.env.ANTHROPIC_MODEL = $targetModel
    $settings.env.ANTHROPIC_DEFAULT_OPUS_MODEL = $targetModel
} else {
    $settings.env.ANTHROPIC_MODEL = $targetModel
    $settings.env.ANTHROPIC_DEFAULT_OPUS_MODEL = $targetModel
    $settings.env.ANTHROPIC_DEFAULT_SONNET_MODEL = $targetModel
    $settings.env.ANTHROPIC_DEFAULT_HAIKU_MODEL = $targetModel
    $settings.env.ANTHROPIC_REASONING_MODEL = $targetModel
}

$utf8 = New-Object System.Text.UTF8Encoding($false)
$json = $settings | ConvertTo-Json -Depth 10
[System.IO.File]::WriteAllText($settingsPath, $json, $utf8)
Write-Host "settings.json: $oldModel -> $targetModel" -ForegroundColor Green

# ---------- 更新 config.py ----------
if (Test-Path $configPyPath) {
    $content = [System.IO.File]::ReadAllText($configPyPath, $utf8)
    $newContent = $content -replace 'llm_model: str = "[^"]*"', "llm_model: str = `"$targetModel`""
    if ($newContent -ne $content) {
        [System.IO.File]::WriteAllText($configPyPath, $newContent, $utf8)
        Write-Host "config.py: llm_model -> $targetModel" -ForegroundColor Green
    }
}

# ---------- 确保 adapter.py 注册 ----------
if (Test-Path $adapterPyPath) {
    $content = [System.IO.File]::ReadAllText($adapterPyPath, $utf8)
    if ($content -notmatch [regex]::Escape("`"$targetModel`"")) {
        $caps = $modelCapabilities[$targetModel]
        if ($caps) {
            $v = if ($caps.vision) { "True" } else { "False" }
            $t = if ($caps.tools) { "True" } else { "False" }
            $s = if ($caps.stream) { "True" } else { "False" }
            $entry = @"

    `"$targetModel`": ModelInfo(
        name=`"$targetModel`",
        provider=`"deepseek`",
        max_tokens=$($caps.max_tokens),
        supports_vision=$v,
        supports_tools=$t,
        supports_streaming=$s,
    ),
"@
            $content = $content -replace '(\n\})', "$entry`n}"
            [System.IO.File]::WriteAllText($adapterPyPath, $content, $utf8)
            Write-Host "adapter.py: registered $targetModel" -ForegroundColor Green
        }
    }
}

# ---------- 完成 ----------
Write-Host ""
Write-Host "=== Model switched: $oldModel -> $targetModel ===" -ForegroundColor Yellow
Write-Host "[!] Restart Claude Code for the change to take effect." -ForegroundColor Red
