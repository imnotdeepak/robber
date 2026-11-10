# Keeps Windows from sleeping while the flag file exists (the display may still turn off).
param([string]$Flag)
Add-Type -Name Power -Namespace Robber -MemberDefinition '[DllImport("kernel32.dll")] public static extern uint SetThreadExecutionState(uint flags);'
[Robber.Power]::SetThreadExecutionState([uint32]2147483649) | Out-Null  # ES_CONTINUOUS | ES_SYSTEM_REQUIRED
while (Test-Path $Flag) { Start-Sleep -Seconds 30 }
[Robber.Power]::SetThreadExecutionState([uint32]2147483648) | Out-Null
