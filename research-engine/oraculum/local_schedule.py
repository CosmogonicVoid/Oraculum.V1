"""Install an ordinary current-user Windows task; no password or elevation."""
import json
import os
from pathlib import Path
import subprocess
import sys

from .contracts import ValidationError

TASK_NAME = "Oraculum Daily Research"
SCRIPT = r'''
$ErrorActionPreference = 'Stop'
$taskName = 'Oraculum Daily Research'
$taskRoot = $env:ORACULUM_TASK_ROOT
$taskPython = $env:ORACULUM_TASK_PYTHON
$description = 'Oraculum local paper research v1 | ' + $taskRoot
$existing = Get-ScheduledTask -TaskName $taskName -ErrorAction SilentlyContinue
if ($existing -and $existing.Description -ne $description) {
    throw 'A task with this name belongs to another installation. Remove it from its original Oraculum folder first.'
}
if ($env:ORACULUM_TASK_OPERATION -eq 'remove') {
    if ($existing) { Unregister-ScheduledTask -TaskName $taskName -Confirm:$false }
    @{task_name=$taskName; installed=$false} | ConvertTo-Json -Compress
    exit 0
}
if ($env:ORACULUM_TASK_OPERATION -eq 'install') {
    $taskUser = [System.Security.Principal.WindowsIdentity]::GetCurrent().Name
    $action = New-ScheduledTaskAction -Execute $taskPython -Argument '-m oraculum.local auto-daily' -WorkingDirectory $taskRoot
    $principal = New-ScheduledTaskPrincipal -UserId $taskUser -LogonType Interactive -RunLevel Limited
    $triggers = @((New-ScheduledTaskTrigger -Daily -At '19:00'), (New-ScheduledTaskTrigger -Daily -At '21:00'), (New-ScheduledTaskTrigger -AtLogOn -User $taskUser))
    $settings = New-ScheduledTaskSettingsSet -StartWhenAvailable -MultipleInstances IgnoreNew -RunOnlyIfNetworkAvailable -ExecutionTimeLimit (New-TimeSpan -Hours 2)
    Register-ScheduledTask -TaskName $taskName -Action $action -Trigger $triggers -Principal $principal -Settings $settings -Description $description -Force | Out-Null
    $existing = Get-ScheduledTask -TaskName $taskName
}
if ($existing) {
    $info = Get-ScheduledTaskInfo -TaskName $taskName
    @{task_name=$taskName; installed=$true; state=[string]$existing.State; next_run=[string]$info.NextRunTime; last_result=$info.LastTaskResult; time_zone=[System.TimeZoneInfo]::Local.Id; schedule='19:00 and 21:00 computer-local time; also at sign-in'; requires='Computer awake, plugged in, user signed in and network available'} | ConvertTo-Json -Compress
} else { @{task_name=$taskName; installed=$false} | ConvertTo-Json -Compress }
'''


def schedule(operation, *, project=None):
    if os.name != "nt":
        raise ValidationError("Task installation is available on Windows. Run this command on your own Windows PC.")
    if operation not in ("install", "remove", "status"):
        raise ValidationError("Invalid schedule operation")
    project = Path(project or Path(__file__).resolve().parents[1]).resolve()
    environment = dict(os.environ, ORACULUM_TASK_ROOT=str(project),
                       ORACULUM_TASK_PYTHON=str(Path(sys.executable).resolve()),
                       ORACULUM_TASK_OPERATION=operation)
    try:
        result = subprocess.run(["powershell.exe", "-NoProfile", "-NonInteractive", "-Command", SCRIPT],
                                env=environment, capture_output=True, text=True, errors="replace", timeout=45, check=False)
    except subprocess.TimeoutExpired as exc:
        raise ValidationError("Task Scheduler response timed out. Run schedule-status to check the result before retrying.") from exc
    if result.returncode:
        raise ValidationError("Windows Task Scheduler could not complete the operation: "+result.stderr.strip()[:1800])
    try:
        return json.loads(result.stdout.strip())
    except ValueError as exc:
        raise ValidationError("Task Scheduler returned an unexpected response; inspect Windows Task Scheduler") from exc
