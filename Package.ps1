param(
  [string]$Version = "",
  [switch]$SkipBuild,
  [switch]$SkipInstaller,
  [string]$InnoSetupPath = ""
)

$ErrorActionPreference = "Stop"

$root = Split-Path -Parent $MyInvocation.MyCommand.Path
$appName = "LiquidMemoWidget"
$appDir = Join-Path $root "dist\$appName"
$installerDir = Join-Path $root "dist\installer"

function Resolve-AppVersion {
  param([string]$RequestedVersion)

  if (-not [string]::IsNullOrWhiteSpace($RequestedVersion)) {
    return $RequestedVersion.Trim().TrimStart("v")
  }

  if (-not [string]::IsNullOrWhiteSpace($env:RELEASE_VERSION)) {
    return $env:RELEASE_VERSION.Trim().TrimStart("v")
  }

  $tag = ""
  try {
    $tag = git tag --points-at HEAD "v*" | Select-Object -First 1
  } catch {
    $tag = ""
  }

  if (-not [string]::IsNullOrWhiteSpace($tag)) {
    return $tag.Trim().TrimStart("v")
  }

  return "0.0.1"
}

function Resolve-IsccPath {
  param([string]$RequestedPath)

  $candidates = @()

  if (-not [string]::IsNullOrWhiteSpace($RequestedPath)) {
    $candidates += $RequestedPath
  }

  if (-not [string]::IsNullOrWhiteSpace($env:ISCC)) {
    $candidates += $env:ISCC
  }

  $command = Get-Command "ISCC.exe" -ErrorAction SilentlyContinue
  if ($command) {
    $candidates += $command.Source
  }

  if ($env:ProgramFiles) {
    $candidates += (Join-Path $env:ProgramFiles "Inno Setup 6\ISCC.exe")
  }

  $programFilesX86 = [Environment]::GetEnvironmentVariable("ProgramFiles(x86)")
  if ($programFilesX86) {
    $candidates += (Join-Path $programFilesX86 "Inno Setup 6\ISCC.exe")
  }

  foreach ($candidate in $candidates) {
    if ($candidate -and (Test-Path -LiteralPath $candidate)) {
      return (Resolve-Path -LiteralPath $candidate).Path
    }
  }

  throw "Inno Setup compiler ISCC.exe was not found. Install Inno Setup 6, set `$env:ISCC, or pass -InnoSetupPath `"C:\Path\To\ISCC.exe`"."
}

function Assert-AppBuild {
  $exe = Join-Path $appDir "$appName.exe"
  if (-not (Test-Path -LiteralPath $exe)) {
    throw "Build output was not found: $exe"
  }
}

function Write-Sha256Sidecar {
  # Emit a "<hash>  <filename>" sidecar (sha256sum layout) next to $Path. The in-app updater
  # downloads this for the installer and verifies it before running the silent install.
  param([string]$Path)
  $hash = (Get-FileHash -LiteralPath $Path -Algorithm SHA256).Hash.ToLower()
  $name = Split-Path -Leaf $Path
  "$hash  $name" | Set-Content -LiteralPath "$Path.sha256" -Encoding ascii -NoNewline
}

$appVersion = Resolve-AppVersion -RequestedVersion $Version
$env:APP_VERSION = $appVersion

Write-Host "Packaging Liquid Memo Widget v$appVersion"
Write-Host "Workspace: $root"

if (-not $SkipBuild) {
  Write-Host ""
  Write-Host "==> Building PyInstaller app"
  & (Join-Path $root "Build.ps1")
}

Assert-AppBuild

if (-not (Test-Path -LiteralPath $installerDir)) {
  New-Item -ItemType Directory -Path $installerDir | Out-Null
}

$portablePath = Join-Path $root "dist\$appName-Portable-v$appVersion.zip"
if (Test-Path -LiteralPath $portablePath) {
  Remove-Item -LiteralPath $portablePath -Force
}

Write-Host ""
Write-Host "==> Creating portable zip"
# Drop a marker the runtime uses to recognize the portable build (so it offers a manual
# download instead of silently running the installer over itself). It must be in the zip but
# NOT in the installer, so write it just for the zip and remove it before Inno builds below.
$portableFlag = Join-Path $appDir "portable.flag"
"portable" | Set-Content -LiteralPath $portableFlag -Encoding ascii -NoNewline
Compress-Archive -Path (Join-Path $appDir "*") -DestinationPath $portablePath -CompressionLevel Optimal -Force
Remove-Item -LiteralPath $portableFlag -Force
Write-Sha256Sidecar -Path $portablePath

$installerPath = Join-Path $installerDir "$appName-Setup-v$appVersion.exe"

if (-not $SkipInstaller) {
  $iscc = Resolve-IsccPath -RequestedPath $InnoSetupPath
  Write-Host ""
  Write-Host "==> Creating installer with Inno Setup"
  & $iscc (Join-Path $root "installer\LiquidMemoWidget.iss")

  if (-not (Test-Path -LiteralPath $installerPath)) {
    throw "Installer output was not found: $installerPath"
  }
  Write-Sha256Sidecar -Path $installerPath
}

Write-Host ""
Write-Host "Package outputs:"
Write-Host "  Portable:  $portablePath"
if (-not $SkipInstaller) {
  Write-Host "  Installer: $installerPath"
} else {
  Write-Host "  Installer: skipped"
}
