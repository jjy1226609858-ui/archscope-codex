param(
    [Parameter(Mandatory = $true)][string]$OutputRoot,
    [Parameter(Mandatory = $true)][string]$BuildRoot
)

$ErrorActionPreference = 'Stop'
$sourceRoot = (Resolve-Path -LiteralPath (Join-Path $PSScriptRoot '..')).Path
$output = [IO.Path]::GetFullPath($OutputRoot)
$build = [IO.Path]::GetFullPath($BuildRoot)
if (Test-Path -LiteralPath $output) {
    throw "OutputRoot already exists: $output"
}
if (-not (Test-Path -LiteralPath (Join-Path $sourceRoot 'web\dist\index.html'))) {
    throw 'web/dist is missing; run the production web build first'
}
$python = Join-Path $sourceRoot '.venv\Scripts\python.exe'
$pyinstaller = Join-Path $sourceRoot '.venv\Scripts\pyinstaller.exe'
if (-not (Test-Path -LiteralPath $pyinstaller)) {
    throw 'PyInstaller is missing from the project virtual environment'
}

$runtimeDist = Join-Path $build 'dist'
$runtimeWork = Join-Path $build 'build'
& $pyinstaller --noconfirm --clean --onedir --name archscope --paths (Join-Path $sourceRoot 'src') --hidden-import archscope.mcp.server --collect-all uvicorn --distpath $runtimeDist --workpath $runtimeWork --specpath $build (Join-Path $sourceRoot 'src\archscope\cli.py')
if ($LASTEXITCODE -ne 0) { throw "PyInstaller failed: $LASTEXITCODE" }

$pluginTarget = Join-Path $output 'plugins\archscope'
[IO.Directory]::CreateDirectory($pluginTarget) | Out-Null
robocopy (Join-Path $sourceRoot 'plugin') $pluginTarget /E /XD runtime resources __pycache__ /XF *.pyc /NFL /NDL /NJH /NJS /NP | Out-Null
if ($LASTEXITCODE -gt 7) { throw "plugin copy failed: $LASTEXITCODE" }
Copy-Item -LiteralPath (Join-Path $sourceRoot 'LICENSE') -Destination (Join-Path $pluginTarget 'LICENSE')
robocopy (Join-Path $runtimeDist 'archscope') (Join-Path $pluginTarget 'runtime') /E /NFL /NDL /NJH /NJS /NP | Out-Null
if ($LASTEXITCODE -gt 7) { throw "runtime copy failed: $LASTEXITCODE" }
robocopy (Join-Path $sourceRoot 'schemas') (Join-Path $pluginTarget 'resources\schemas') /E /NFL /NDL /NJH /NJS /NP | Out-Null
if ($LASTEXITCODE -gt 7) { throw "schema copy failed: $LASTEXITCODE" }
robocopy (Join-Path $sourceRoot 'web\dist') (Join-Path $pluginTarget 'resources\web\dist') /E /NFL /NDL /NJH /NJS /NP | Out-Null
if ($LASTEXITCODE -gt 7) { throw "web copy failed: $LASTEXITCODE" }
$sdkTarget = Join-Path $pluginTarget 'resources\python\archscope'
[IO.Directory]::CreateDirectory($sdkTarget) | Out-Null
Copy-Item -LiteralPath (Join-Path $sourceRoot 'src\archscope\__init__.py') -Destination (Join-Path $sdkTarget '__init__.py')
robocopy (Join-Path $sourceRoot 'src\archscope\telemetry') (Join-Path $sdkTarget 'telemetry') /E /XD __pycache__ /XF *.pyc /NFL /NDL /NJH /NJS /NP | Out-Null
if ($LASTEXITCODE -gt 7) { throw "telemetry SDK copy failed: $LASTEXITCODE" }
robocopy (Join-Path $sourceRoot 'examples\mini_planner') (Join-Path $pluginTarget 'resources\examples\mini_planner') /E /XD .archscope __pycache__ /XF *.pyc /NFL /NDL /NJH /NJS /NP | Out-Null
if ($LASTEXITCODE -gt 7) { throw "demo copy failed: $LASTEXITCODE" }
& $python (Join-Path $sourceRoot 'tools\build_third_party_notices.py') $sourceRoot $pluginTarget
if ($LASTEXITCODE -ne 0) { throw "third-party license collection failed: $LASTEXITCODE" }

$marketplaceDir = Join-Path $output '.agents\plugins'
[IO.Directory]::CreateDirectory($marketplaceDir) | Out-Null
$marketplace = [ordered]@{
    name = 'archscope-local'
    interface = [ordered]@{ displayName = 'ArchScope Local' }
    plugins = @([ordered]@{
        name = 'archscope'
        source = [ordered]@{ source = 'local'; path = './plugins/archscope' }
        policy = [ordered]@{ installation = 'AVAILABLE'; authentication = 'ON_INSTALL' }
        category = 'Developer Tools'
    })
}
[IO.File]::WriteAllText((Join-Path $marketplaceDir 'marketplace.json'), ($marketplace | ConvertTo-Json -Depth 8), [Text.UTF8Encoding]::new($false))
$manifest = Get-Content -Raw -Encoding UTF8 (Join-Path $pluginTarget 'plugin.json') | ConvertFrom-Json
$buildInfo = [ordered]@{
    plugin_version = $manifest.version
    platform = 'windows-x64'
    runtime = 'PyInstaller onedir'
    python = (& $python --version 2>&1).ToString()
    executable_sha256 = (Get-FileHash (Join-Path $pluginTarget 'runtime\archscope.exe') -Algorithm SHA256).Hash
    generated_at = [DateTimeOffset]::UtcNow.ToString('o')
}
[IO.File]::WriteAllText((Join-Path $output 'BUILD_INFO.json'), ($buildInfo | ConvertTo-Json -Depth 5), [Text.UTF8Encoding]::new($false))
foreach ($guide in @('README.md', 'INSTALL.md', 'INSTALL.zh-CN.md', 'LICENSE')) {
    Copy-Item -LiteralPath (Join-Path $sourceRoot $guide) -Destination (Join-Path $output $guide)
}
Write-Output $output
