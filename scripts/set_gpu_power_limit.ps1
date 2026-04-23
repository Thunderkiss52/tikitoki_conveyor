param(
    [double]$Percent = 90
)

$ErrorActionPreference = "Stop"

function Test-IsAdministrator {
    $identity = [Security.Principal.WindowsIdentity]::GetCurrent()
    $principal = New-Object Security.Principal.WindowsPrincipal($identity)
    return $principal.IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)
}

if (-not (Test-IsAdministrator)) {
    $arguments = @(
        "-ExecutionPolicy", "Bypass",
        "-File", ('"{0}"' -f $PSCommandPath),
        "-Percent", $Percent
    )
    $process = Start-Process -FilePath "powershell.exe" -Verb RunAs -ArgumentList $arguments -PassThru
    $process.WaitForExit()
    exit $process.ExitCode
}

if ($Percent -le 0 -or $Percent -gt 100) {
    throw "Percent must be in the range (0, 100]."
}

$nvidiaSmi = (Get-Command nvidia-smi.exe -ErrorAction Stop).Source
$query = & $nvidiaSmi --query-gpu=name,power.default_limit,power.limit --format=csv,noheader,nounits
$parts = $query.Split(",") | ForEach-Object { $_.Trim() }

$gpuName = $parts[0]
$defaultLimit = [double]$parts[1]
$currentLimit = [double]$parts[2]
$targetLimit = [Math]::Round(($defaultLimit * $Percent / 100.0), 2)

Write-Host "GPU: $gpuName"
Write-Host "Default power limit: $defaultLimit W"
Write-Host "Current power limit: $currentLimit W"
Write-Host "Target power limit: $targetLimit W"

& $nvidiaSmi -pl $targetLimit

$verify = & $nvidiaSmi --query-gpu=name,power.limit,power.default_limit --format=csv,noheader
Write-Host $verify
