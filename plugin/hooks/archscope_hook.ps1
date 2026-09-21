$ErrorActionPreference = 'Stop'

try {
    $buffer = New-Object char[] 1048577
    $readCount = [Console]::In.ReadBlock($buffer, 0, $buffer.Length)
    if ($readCount -eq $buffer.Length) { throw 'hook input exceeds 1 MiB' }
    $raw = [string]::new($buffer, 0, $readCount)
    if ([Text.Encoding]::UTF8.GetByteCount($raw) -gt 1048576) { throw 'hook input exceeds 1 MiB' }
    $event = $raw | ConvertFrom-Json
    if ($null -eq $event -or $event -isnot [pscustomobject]) { throw 'hook input must be an object' }
    $sessionId = ([string]$event.session_id)
    if ($sessionId.Length -gt 256) { $sessionId = $sessionId.Substring(0, 256) }
    $safeSession = $sessionId -replace '[^A-Za-z0-9_.-]', '_'
    if (-not $safeSession) { $safeSession = 'unknown' }
    if ($safeSession.Length -gt 80) {
        $sha = [Security.Cryptography.SHA256]::Create()
        try { $digest = [BitConverter]::ToString($sha.ComputeHash([Text.Encoding]::UTF8.GetBytes($sessionId))).Replace('-', '').ToLowerInvariant() }
        finally { $sha.Dispose() }
        $safeSession = $safeSession.Substring(0, 64) + '-' + $digest.Substring(0, 16)
    }
    $dataRoot = if ($env:PLUGIN_DATA) { $env:PLUGIN_DATA } elseif ($env:CLAUDE_PLUGIN_DATA) { $env:CLAUDE_PLUGIN_DATA } else { Join-Path $env:TEMP 'archscope-plugin-data' }
    $hookRoot = Join-Path $dataRoot 'hooks'
    [IO.Directory]::CreateDirectory($hookRoot) | Out-Null
    $record = [ordered]@{
        recorded_at = [DateTimeOffset]::UtcNow.ToString('o')
        session_id = $sessionId
        turn_id = ([string]$event.turn_id).Substring(0, [Math]::Min(([string]$event.turn_id).Length, 256))
        event = ([string]$event.hook_event_name).Substring(0, [Math]::Min(([string]$event.hook_event_name).Length, 64))
        tool_name = ([string]$event.tool_name).Substring(0, [Math]::Min(([string]$event.tool_name).Length, 128))
        tool_use_id = ([string]$event.tool_use_id).Substring(0, [Math]::Min(([string]$event.tool_use_id).Length, 256))
        cwd = ([string]$event.cwd).Substring(0, [Math]::Min(([string]$event.cwd).Length, 1024))
        permission_mode = ([string]$event.permission_mode).Substring(0, [Math]::Min(([string]$event.permission_mode).Length, 64))
    }
    $line = ($record | ConvertTo-Json -Compress) + [Environment]::NewLine
    [IO.File]::AppendAllText((Join-Path $hookRoot "$safeSession.jsonl"), $line, [Text.UTF8Encoding]::new($false))
    $status = [ordered]@{ status = 'active'; last_event = $record.event; last_seen_at = $record.recorded_at; session_id = $sessionId }
    $statusPath = Join-Path $hookRoot 'status.json'
    $temporary = "$statusPath.tmp.$PID"
    [IO.File]::WriteAllText($temporary, ($status | ConvertTo-Json), [Text.UTF8Encoding]::new($false))
    Move-Item -LiteralPath $temporary -Destination $statusPath -Force
    if ($record.event -eq 'SessionStart') {
        $identity = if ($sessionId.Length -le 128 -and $sessionId -cmatch '^[A-Za-z0-9._:/-]+$') {
            "For task leases in this session use actor_id 'codex-session:$sessionId'."
        } else {
            'Session identity is missing or malformed; do not claim task leases from this hook context.'
        }
        $context = "ArchScope lifecycle hook executed. $identity Hook execution does not prove host trust; hooks only record lifecycle metadata and do not approve architecture, expand scope, or mark tasks verified."
        [ordered]@{ hookSpecificOutput = [ordered]@{ hookEventName = 'SessionStart'; additionalContext = $context } } | ConvertTo-Json -Depth 4 -Compress
    }
    exit 0
} catch {
    [Console]::Error.WriteLine("ArchScope hook failed: $($_.Exception.Message)")
    exit 1
}
