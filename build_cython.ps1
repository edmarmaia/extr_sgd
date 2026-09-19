# Gera a distribuicao onedir com Cython e PyInstaller.
param(
    [string]$Python = 'python',
    [string]$CertificateThumbprint,
    [string]$TimestampServer = 'http://timestamp.digicert.com'
)

$ErrorActionPreference = 'Stop'
Set-StrictMode -Version Latest
$root = Split-Path -Parent $MyInvocation.MyCommand.Path
$frontend = Join-Path $root 'frontend'
$native = Join-Path $root 'build\cython'
$venv = Join-Path $root '.venv-build'
$buildPython = Join-Path $venv 'Scripts\python.exe'
$bundle = Join-Path $root 'dist\Extrator_SGD'
$output = Join-Path $bundle 'Extrator_SGD.exe'

function Invoke-Checked {
    param([string]$Command, [string[]]$Arguments)
    & $Command @Arguments
    if ($LASTEXITCODE -ne 0) {
        throw "Falha em $Command (codigo $LASTEXITCODE)."
    }
}

Push-Location $root
try {
    # O lock cobre somente esta versao e arquitetura do Python.
    Invoke-Checked $Python @('-c', "import sys, struct; assert sys.platform == 'win32' and sys.version_info[:2] == (3, 12) and struct.calcsize('P') == 8, 'Use CPython 3.12 x64 no Windows.'")
    $certificate = $null
    if ($CertificateThumbprint) {
        $thumbprint = $CertificateThumbprint.Replace(' ', '')
        $certificate = Get-Item -LiteralPath "Cert:\CurrentUser\My\$thumbprint"
        if (-not $certificate.HasPrivateKey) {
            throw 'O certificado precisa ter chave privada acessivel ao usuario atual.'
        }
    }

    if (-not (Test-Path -LiteralPath $buildPython)) {
        if (Test-Path -LiteralPath $venv) {
            throw 'A pasta .venv-build existe mas nao e um ambiente valido. Revise-a antes de recriar.'
        }
        Invoke-Checked $Python @('-m', 'venv', $venv)
    }
    Invoke-Checked $buildPython @('-m', 'pip', 'install', '-r', 'requirements-build.lock')
    Invoke-Checked $buildPython @('-m', 'pip', 'check')
    Invoke-Checked $buildPython @('package_release.py', '--check-environment')

    Invoke-Checked 'npm.cmd' @('ci', '--prefix', $frontend)
    Invoke-Checked 'npm.cmd' @('run', 'build', '--prefix', $frontend)

    # Remove somente o diretorio Cython gerado por este build.
    if (Test-Path -LiteralPath $native) {
        Remove-Item -LiteralPath $native -Recurse -Force
    }
    Invoke-Checked $buildPython @('setup_cython.py', 'build_ext', '--build-lib', "$native\lib", '--build-temp', "$native\temp", '--force')
    Invoke-Checked $buildPython @('-m', 'PyInstaller', '--clean', '--noconfirm', '--distpath', 'dist', '--workpath', 'build\pyinstaller-cython', 'Extrator_SGD_Cython.spec')
    if (-not (Test-Path -LiteralPath $output)) {
        throw 'A compilacao terminou sem gerar dist\Extrator_SGD\Extrator_SGD.exe.'
    }

    # Assina apenas o aplicativo e seus modulos nativos.
    if ($null -ne $certificate) {
        $ownModules = @(Get-ChildItem -LiteralPath "$native\lib" -Filter '*.pyd' -File)
        $targets = @($output) + @($ownModules | ForEach-Object { Join-Path "$bundle\_internal" $_.Name })
        foreach ($target in $targets) {
            $signature = Set-AuthenticodeSignature -FilePath $target -Certificate $certificate -HashAlgorithm SHA256 -TimestampServer $TimestampServer
            if ($signature.Status -ne 'Valid' -or $null -eq $signature.TimeStamperCertificate) {
                throw "Assinatura com carimbo de tempo nao validada: $target ($($signature.Status))."
            }
        }
    }

    $packageArgs = @('package_release.py')
    if ($null -ne $certificate) { $packageArgs += '--signed' }
    Invoke-Checked $buildPython $packageArgs
    Write-Output "Aplicativo Cython em pasta gerado: $output"
    if ($null -eq $certificate) {
        Write-Output 'Entrega sem assinatura digital. Use -CertificateThumbprint quando houver certificado confiavel.'
    }
}
finally {
    Pop-Location
}
