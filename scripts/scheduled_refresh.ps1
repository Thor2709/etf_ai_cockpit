<#
Runs one scheduled ETF AI Cockpit data job and logs it to <Root>\logs\scheduled\<Job>-yyyyMMdd-HHmm.log.
  Daily : new price days + FX, rescore, readiness gate, publish. Paper bots are skipped (--dry-run).
  Weekly: stock fundamentals once per week. The Saturday trigger runs it; the Sunday and Monday
          triggers run it only when this week's run has not succeeded yet (stamp file).
Exit code 1 from the daily job while the readiness gate fails is expected: data is fetched and saved.
Register the jobs with register_scheduled_refresh.ps1.
#>
param(
    [Parameter(Mandatory)][ValidateSet('Daily', 'Weekly')][string]$Job,
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
} else {
    $arguments = @("$PSScriptRoot\run_daily_paper.py", '--root', $Root, '--dry-run',
                   '--incremental-prices', '--skip-fundamentals', '--refresh-fx')
}

Write-Log "start $Job"
$started = Get-Date
& $Python @arguments 2>&1 | ForEach-Object { "$_" } | Add-Content -Path $log -Encoding UTF8
$code = $LASTEXITCODE
Write-Log ('end {0} exit={1} duration={2:hh\:mm\:ss}' -f $Job, $code, ((Get-Date) - $started))
if ($Job -eq 'Weekly' -and $code -eq 0) { Set-Content -Path $stamp -Value $today.ToString('yyyy-MM-dd') }
exit $code
