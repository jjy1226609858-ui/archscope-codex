$ErrorActionPreference = 'Stop'

$pluginRoot = (Resolve-Path -LiteralPath (Join-Path $PSScriptRoot '..')).Path
$repositoryRoot = (Resolve-Path -LiteralPath (Join-Path $pluginRoot '..')).Path
$portableExe = Join-Path $pluginRoot 'runtime\archscope.exe'

if (Test-Path -LiteralPath $portableExe) {
    $env:ARCHSCOPE_ROOT = Join-Path $pluginRoot 'resources'
    if (-not $env:ARCHSCOPE_REGISTRY) {
        if (-not $env:PLUGIN_DATA) {
            $env:PLUGIN_DATA = Join-Path $env:LOCALAPPDATA 'ArchScope\plugin-data'
        }
        $env:ARCHSCOPE_REGISTRY = Join-Path $env:PLUGIN_DATA 'projects.json'
        & $portableExe bootstrap --data-root $env:PLUGIN_DATA --demo-root (Join-Path $env:ARCHSCOPE_ROOT 'examples\mini_planner') *> $null
        if ($LASTEXITCODE -ne 0) {
            [Console]::Error.WriteLine('ArchScope could not initialize its writable plugin data directory.')
            exit $LASTEXITCODE
        }
    }
    & $portableExe mcp
    exit $LASTEXITCODE
}

if ($env:ARCHSCOPE_PYTHON -and (Test-Path -LiteralPath $env:ARCHSCOPE_PYTHON)) {
    $pythonExe = $env:ARCHSCOPE_PYTHON
} elseif (Test-Path -LiteralPath (Join-Path $repositoryRoot '.venv\Scripts\python.exe')) {
    $pythonExe = Join-Path $repositoryRoot '.venv\Scripts\python.exe'
} else {
    $pythonCommand = Get-Command python -ErrorAction SilentlyContinue
    if (-not $pythonCommand) {
        [Console]::Error.WriteLine('ArchScope could not find Python. Set ARCHSCOPE_PYTHON to the project interpreter.')
        exit 2
    }
    $pythonExe = $pythonCommand.Source
}

$env:ARCHSCOPE_ROOT = $repositoryRoot
if (-not $env:ARCHSCOPE_REGISTRY) {
    $env:ARCHSCOPE_REGISTRY = Join-Path $repositoryRoot 'examples\projects.json'
}
$sourceRoot = Join-Path $repositoryRoot 'src'
if ($env:PYTHONPATH) {
    $env:PYTHONPATH = "$sourceRoot$([IO.Path]::PathSeparator)$env:PYTHONPATH"
} else {
    $env:PYTHONPATH = $sourceRoot
}

& $pythonExe -m archscope.mcp.server
exit $LASTEXITCODE
