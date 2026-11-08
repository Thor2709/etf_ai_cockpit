<#
Registers the two scheduled ETF AI Cockpit data jobs for the current user. They run while the user is
logged on; no password is stored.
  ETF-Cockpit-Daily-Prices         every day 22:30 (all markets closed: US closed, Tokyo not open yet)
  ETF-Cockpit-Weekly-Fundamentals  Saturday, Sunday and Monday 10:00 (Sunday/Monday only catch up a missed Saturday)
A start missed while the laptop was off runs as soon as it is on again. The jobs run the code next to this
script, so register from the checkout that should run. Registering over an existing task fails; remove it
first with Unregister-ScheduledTask.
Usage: powershell -NoProfile -File register_scheduled_refresh.ps1 -Root <data root> -Python <python.exe>
#>
param(
    [Parameter(Mandatory)][string]$Root,
    [Parameter(Mandatory)][string]$Python
)
$ErrorActionPreference = 'Stop'

$runner = Join-Path $PSScriptRoot 'scheduled_refresh.ps1'
foreach ($path in $runner, $Python, (Join-Path $Root 'configs\universe.yaml')) {
    if (-not (Test-Path $path)) { throw "Not found: $path" }
}
$principal = New-ScheduledTaskPrincipal -UserId "$env:USERDOMAIN\$env:USERNAME" -LogonType Interactive

function Register-Job([string]$Name, [string]$Kind, $Trigger, [int]$Hours) {
    $argument = '-NoProfile -ExecutionPolicy Bypass -WindowStyle Hidden -File "{0}" -Job {1} -Root "{2}" -Python "{3}"' -f $runner, $Kind, $Root, $Python
    $action = New-ScheduledTaskAction -Execute 'powershell.exe' -Argument $argument
    $settings = New-ScheduledTaskSettingsSet -StartWhenAvailable -MultipleInstances IgnoreNew -AllowStartIfOnBatteries `
        -DontStopIfGoingOnBatteries -ExecutionTimeLimit (New-TimeSpan -Hours $Hours)
    Register-ScheduledTask -TaskName $Name -Action $action -Trigger $Trigger -Settings $settings -Principal $principal | Out-Null
    "registered $Name"
}

Register-Job 'ETF-Cockpit-Daily-Prices' 'Daily' (New-ScheduledTaskTrigger -Daily -At '22:30') 4
Register-Job 'ETF-Cockpit-Weekly-Fundamentals' 'Weekly' (New-ScheduledTaskTrigger -Weekly -DaysOfWeek Saturday, Sunday, Monday -At '10:00') 8
