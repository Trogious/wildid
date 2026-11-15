# Build the WildID Windows installer. Run on Windows, from this directory:
#   powershell -ExecutionPolicy Bypass -File build.ps1
# Steps: download a pinned uv.exe (checksum-verified) -> stage payload\ -> compile wildid.iss.
# Needs: network (for uv.exe), Inno Setup 6 (https://jrsoftware.org/isinfo.php).

param(
    # Keep in step with the uv version the repo develops with.
    [string]$UvVersion = "0.11.32",
    [string]$Iscc = "${env:ProgramFiles(x86)}\Inno Setup 6\ISCC.exe"
)

$ErrorActionPreference = "Stop"
$here = Split-Path -Parent $MyInvocation.MyCommand.Path
$repo = Resolve-Path (Join-Path $here "..\..")
$payload = Join-Path $here "payload"

# Version from pyproject.toml so the installer name tracks the app.
$pyproject = Get-Content (Join-Path $repo "pyproject.toml") -Raw
if ($pyproject -match 'version\s*=\s*"([^"]+)"') { $version = $Matches[1] } else { $version = "0.0.0" }
Write-Host "WildID $version, uv $UvVersion"

# --- payload ---------------------------------------------------------------
if (Test-Path $payload) { Remove-Item $payload -Recurse -Force }
New-Item -ItemType Directory -Path (Join-Path $payload "app") | Out-Null

# uv.exe, pinned and checksum-verified against the artifact's published .sha256
$zip = Join-Path $env:TEMP "uv-$UvVersion.zip"
$base = "https://github.com/astral-sh/uv/releases/download/$UvVersion"
Invoke-WebRequest "$base/uv-x86_64-pc-windows-msvc.zip" -OutFile $zip
# PowerShell 7 hands back octet-stream bodies as byte[]; decode before parsing the "<hash>  <file>" line.
$raw = (Invoke-WebRequest "$base/uv-x86_64-pc-windows-msvc.zip.sha256").Content
if ($raw -is [byte[]]) { $raw = [System.Text.Encoding]::ASCII.GetString($raw) }
$expected = ([string]$raw).Trim() -split '\s+' | Select-Object -First 1
if ($expected -notmatch '^[0-9a-fA-F]{64}$') { throw "unexpected .sha256 content for uv: '$raw'" }
$actual = (Get-FileHash $zip -Algorithm SHA256).Hash.ToLower()
if ($actual -ne $expected.ToLower()) { throw "uv.exe checksum mismatch: $actual != $expected" }
$extract = Join-Path $env:TEMP "uv-$UvVersion"
if (Test-Path $extract) { Remove-Item $extract -Recurse -Force }
Expand-Archive $zip -DestinationPath $extract
Copy-Item (Get-ChildItem $extract -Recurse -Filter uv.exe | Select-Object -First 1).FullName $payload

# the locked project (sources only; the env is resolved on the target machine)
foreach ($f in @("pyproject.toml", "uv.lock", "README.md", ".python-version")) {
    Copy-Item (Join-Path $repo $f) (Join-Path $payload "app")
}
robocopy (Join-Path $repo "src") (Join-Path $payload "app\src") /E /XD __pycache__ | Out-Null
if ($LASTEXITCODE -ge 8) { throw "robocopy src failed: $LASTEXITCODE" }

# the Lightroom plugin
robocopy (Join-Path $repo "lrplugin\wildid.lrplugin") (Join-Path $payload "wildid.lrplugin") /E | Out-Null
if ($LASTEXITCODE -ge 8) { throw "robocopy plugin failed: $LASTEXITCODE" }
$LASTEXITCODE = 0  # robocopy's success codes (<8) must not fail the script

# --- compile ---------------------------------------------------------------
if (-not (Test-Path $Iscc)) {
    Write-Warning "Inno Setup not found at '$Iscc'. Payload is staged; compile manually with:"
    Write-Warning "  ISCC.exe /DMyAppVersion=$version `"$here\wildid.iss`""
    exit 0
}
& $Iscc "/DMyAppVersion=$version" (Join-Path $here "wildid.iss")
if ($LASTEXITCODE -ne 0) { throw "ISCC failed: $LASTEXITCODE" }
Write-Host "Installer: $(Join-Path $here "output\WildID-Setup-$version.exe")"
