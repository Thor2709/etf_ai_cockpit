<#
Runs one scheduled ETF AI Cockpit data job and logs it to <Root>\logs\scheduled\<Job>-yyyyMMdd-HHmm.log.
  Daily : S&P capture, forward score run, readiness gate, paper bots (when enabled), then new price days + FX, rescore, publish.
  Weekly: stock fundamentals and FRED macro vintages once per week. The Saturday trigger runs it; the Sunday and Monday
          triggers run it only when this week's run has not succeeded yet (stamp file).
  Fill  : observes the session opens for the paper fills; it writes only its own store and never waits for a data job.
Exit code 1 from the daily job while the readiness gate or a paper stage fails is expected: the refresh still runs.
Register the jobs with register_scheduled_refresh.ps1.
#>
param(
    [Parameter(Mandatory)][ValidateSet('Daily', 'Weekly', 'Fill')][string]$Job,
    [Parameter(Mandatory)][string]$Root,
    [Parameter(Mandatory)][string]$Python
)

$env:CUDA_VISIBLE_DEVICES = '-1'   # an empty value deletes the variable and exposes the GPU
$env:ETF_COCKPIT_OPEN_BROWSER = '0'
$env:PYTHONIOENCODING = 'utf-8'
$env:ETF_COCKPIT_ROOT = $Root
try { [Console]::OutputEncoding = [Text.Encoding]::UTF8 } catch { }

$logDir = Join-Path $Root 'logs\scheduled'
New-Item -ItemType Directory -Force -Path $logDir | Out-Null
$log = Join-Path $logDir ('{0}-{1:yyyyMMdd-HHmm}.log' -f $Job, (Get-Date))
function Write-Log([string]$Text) { Add-Content -Path $log -Encoding UTF8 -Value ('{0:s} {1}' -f (Get-Date), $Text) }

$today = (Get-Date).Date
$stamp = Join-Path $logDir 'weekly-fundamentals.ok'
if ($Job -eq 'Weekly') {
    $saturday = $today.AddDays(-(([int]$today.DayOfWeek + 1) % 7))   # most recent Saturday, today included
    if (Test-Path $stamp) {
        $last = [datetime]::ParseExact((Get-Content $stamp -TotalCount 1).Trim(), 'yyyy-MM-dd', $null)
        if ($last -ge $saturday) {
            Write-Log ('already done for week of {0:yyyy-MM-dd}' -f $saturday)
            exit 0
        }
    }
    $arguments = @("$PSScriptRoot\refresh_stock_fundamentals.py", '--root', $Root)
} elseif ($Job -eq 'Fill') {
    $arguments = @("$PSScriptRoot\run_morning_fill.py", '--root', $Root)
} else {
    $arguments = @("$PSScriptRoot\run_daily_paper.py", '--root', $Root,
                   '--incremental-prices', '--skip-fundamentals', '--refresh-fx')
}

# Daily and Weekly call Yahoo in bulk: run one at a time to keep 1 call/s (both may start at once after the laptop was
# off). Fill must observe before the fill time, so it never waits (SDD C7); its start check bounds it instead.
$mutex = $null
if ($Job -ne 'Fill') {
    $mutex = New-Object Threading.Mutex($false, 'Global\ETF-Cockpit-Data-Jobs')
    try {
        if (-not $mutex.WaitOne(0)) { Write-Log 'waiting for the other data job to end'; $null = $mutex.WaitOne() }
    } catch [Threading.AbandonedMutexException] { }   # the other job was killed; the mutex is ours now
}

Write-Log "start $Job"
$started = Get-Date
# one short append per line keeps the log readable while the job runs (Add-Content in a pipeline locks it)
& $Python @arguments 2>&1 | ForEach-Object { [IO.File]::AppendAllText($log, "$_`r`n", [Text.Encoding]::UTF8) }
$code = $LASTEXITCODE
Write-Log ('end {0} exit={1} duration={2:hh\:mm\:ss}' -f $Job, $code, ((Get-Date) - $started))
if ($Job -eq 'Weekly' -and $code -eq 0) { Set-Content -Path $stamp -Value $today.ToString('yyyy-MM-dd') }
if ($null -ne $mutex) { $mutex.ReleaseMutex() }
if ($Job -eq 'Weekly') {
    # FRED vintages (context only) need no Yahoo mutex; the exit code is logged and never changes the job result
    & $Python "$PSScriptRoot\refresh_macro.py" --root $Root 2>&1 | ForEach-Object { [IO.File]::AppendAllText($log, "$_`r`n", [Text.Encoding]::UTF8) }
    Write-Log "refresh_macro exit=$LASTEXITCODE"
}
exit $code
