$ErrorActionPreference = "Stop"

$projectRoot = Split-Path -Parent $PSScriptRoot
$buildEnvironment = Join-Path $projectRoot ".venv-build"
$buildPython = Join-Path $buildEnvironment "Scripts\python.exe"
$installerScript = Join-Path $PSScriptRoot "Mihena.iss"

Set-Location $projectRoot

if (-not (Test-Path -LiteralPath $buildPython)) {
    & python -m venv $buildEnvironment
    if ($LASTEXITCODE -ne 0) {
        throw "Impossible de créer l’environnement de construction Python."
    }
}

# L’environnement de construction contient les dépendances de l’application
# et PyInstaller. Ces dépendances sont intégrées au programme distribué.
& $buildPython -m pip install -e '.[build]'
if ($LASTEXITCODE -ne 0) {
    throw "Impossible d’installer les outils de construction."
}

$appVersion = & $buildPython -c "from compress_clone import __version__; print(__version__)"
if ($LASTEXITCODE -ne 0) {
    throw "Impossible de lire la version de Mihena."
}

& $buildPython -m PyInstaller `
    --noconfirm `
    --clean `
    --windowed `
    --onedir `
    --name Mihena `
    --distpath (Join-Path $projectRoot "dist") `
    --workpath (Join-Path $projectRoot "build\pyinstaller") `
    --collect-all py7zr `
    --collect-all pycryptodomex `
    --collect-all backports.zstd `
    --collect-all tkinterdnd2 `
    "Demarrer.pyw"
if ($LASTEXITCODE -ne 0) {
    throw "PyInstaller n’a pas pu créer l’application Windows."
}

$compilerCandidates = @($env:INNO_SETUP_COMPILER)
$programFilesX86 = [Environment]::GetFolderPath("ProgramFilesX86")
if ($programFilesX86) {
    $compilerCandidates += Join-Path $programFilesX86 "Inno Setup 6\ISCC.exe"
    $compilerCandidates += Join-Path $programFilesX86 "Inno Setup 7\ISCC.exe"
}
if ($env:ProgramFiles) {
    $compilerCandidates += Join-Path $env:ProgramFiles "Inno Setup 6\ISCC.exe"
    $compilerCandidates += Join-Path $env:ProgramFiles "Inno Setup 7\ISCC.exe"
}
if ($env:LOCALAPPDATA) {
    $compilerCandidates += Join-Path $env:LOCALAPPDATA "Programs\Inno Setup 6\ISCC.exe"
    $compilerCandidates += Join-Path $env:LOCALAPPDATA "Programs\Inno Setup 7\ISCC.exe"
}
$compilerCommand = Get-Command "ISCC.exe" -ErrorAction SilentlyContinue
$compiler = if ($compilerCommand) { $compilerCommand.Source } else {
    $compilerCandidates |
        Where-Object { $_ -and (Test-Path -LiteralPath $_) } |
        Select-Object -First 1
}

if (-not $compiler) {
    throw "L’application est prête dans dist\Mihena. Installe Inno Setup 6 ou 7 pour créer Mihena-Setup.exe, puis relance ce script."
}

$versionArgument = '--define=AppVersion="' + $appVersion.Trim() + '"'
& $compiler $versionArgument $installerScript
if ($LASTEXITCODE -ne 0) {
    throw "Inno Setup n’a pas pu créer l’installateur."
}

Write-Host "Installateur créé : dist\installer\Mihena-Setup.exe"
