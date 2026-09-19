# Valida o executavel Windows sem iniciar consultas.
param(
    [string]$Exe
)

$ErrorActionPreference = 'Stop'
Add-Type -AssemblyName UIAutomationClient
Add-Type @'
using System;
using System.Runtime.InteropServices;

public static class NativeWindowIcon {
    [DllImport("user32.dll", CharSet = CharSet.Auto)]
    public static extern IntPtr SendMessage(IntPtr hWnd, uint msg, IntPtr wParam, IntPtr lParam);
}
'@
if (-not $Exe) {
    $Exe = Join-Path $PSScriptRoot '..\dist\Extrator_SGD\Extrator_SGD.exe'
}
if (-not (Test-Path -LiteralPath $Exe)) { throw 'Compile o executavel desktop primeiro.' }
$Exe = (Resolve-Path -LiteralPath $Exe).Path
$profile = Join-Path ([IO.Path]::GetTempPath()) ('sgd-packaged-smoke-' + [Guid]::NewGuid().ToString('N'))
$null = [IO.Directory]::CreateDirectory($profile)
$previousLocalAppData = $env:LOCALAPPDATA
$process = $null
try {
    $env:LOCALAPPDATA = $profile
    try {
        $process = Start-Process -FilePath $Exe -PassThru
    } finally {
        $env:LOCALAPPDATA = $previousLocalAppData
    }
    $deadline = (Get-Date).AddSeconds(60)
    $connected = $false
    while ((Get-Date) -lt $deadline) {
        $process.Refresh()
        if ($process.HasExited) { throw "O executavel encerrou com codigo $($process.ExitCode)." }
        if ($process.MainWindowHandle -ne 0) {
            $window = [System.Windows.Automation.AutomationElement]::FromHandle($process.MainWindowHandle)
            $condition = [System.Windows.Automation.PropertyCondition]::new(
                [System.Windows.Automation.AutomationElement]::NameProperty, 'Desktop conectado')
            $badge = $window.FindFirst([System.Windows.Automation.TreeScope]::Descendants, $condition)
            if ($null -ne $badge) { $connected = $true; break }
        }
        Start-Sleep -Milliseconds 500
    }
    if (-not $connected) { throw 'A interface React nao conectou ao desktop empacotado.' }
    $iconHandle = [NativeWindowIcon]::SendMessage($process.MainWindowHandle, 0x7F, [IntPtr]2, [IntPtr]::Zero)
    if ($iconHandle -eq [IntPtr]::Zero) {
        $iconHandle = [NativeWindowIcon]::SendMessage($process.MainWindowHandle, 0x7F, [IntPtr]0, [IntPtr]::Zero)
    }
    if ($iconHandle -eq [IntPtr]::Zero) { throw 'A janela desktop empacotada nao possui icone nativo.' }
    'PASS: executavel empacotado renderizou React, conectou ao Python e exibiu o icone.'
} finally {
    try {
        if ($null -ne $process -and -not $process.HasExited) {
            $null = $process.CloseMainWindow()
            if (-not $process.WaitForExit(10000)) {
                Stop-Process -Id $process.Id
                throw 'O processo do smoke nao encerrou normalmente.'
            }
        }
    } finally {
        if ($null -ne $process) { $process.Dispose() }
        # Subprocessos do WebView2 podem manter arquivos abertos por alguns instantes.
        Start-Sleep -Milliseconds 500
        Remove-Item -LiteralPath $profile -Recurse -Force -ErrorAction Continue
    }
}
