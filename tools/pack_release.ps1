<#
.SYNOPSIS
    Build split 7-Zip volumes for a GitHub Release and write SHA256SUMS.txt.

.EXAMPLE
    pwsh tools/pack_release.ps1 -Version 0.3.0

.NOTES
    GitHub caps a single release asset at 2 GB. Volumes default to 1800 MiB.
#>
[CmdletBinding()]
param(
    [string]$Version = "0.3.0",
    [int]$VolumeMB = 1800,
    [string]$Source = "dist\mangatl-portable",
    [string]$OutDir = "dist\release",
    [string]$SevenZip = ""
)

$ErrorActionPreference = "Stop"
$repoRoot = Split-Path -Parent $PSScriptRoot
Set-Location $repoRoot

$sourcePath = [System.IO.Path]::GetFullPath((Join-Path $repoRoot $Source))
if (-not (Test-Path -LiteralPath $sourcePath -PathType Container)) {
    throw "Portable folder not found: $sourcePath"
}

$outPath = [System.IO.Path]::GetFullPath((Join-Path $repoRoot $OutDir))
New-Item -ItemType Directory -Force -Path $outPath | Out-Null

function Find-SevenZip {
    param([string]$Explicit)

    $paths = @()
    if ($Explicit) { $paths += $Explicit }
    foreach ($name in @("7z", "7za")) {
        $command = Get-Command $name -ErrorAction SilentlyContinue
        if ($command) { $paths += $command.Source }
    }
    $paths += @(
        "C:\Program Files\7-Zip\7z.exe",
        "C:\Program Files (x86)\7-Zip\7z.exe",
        "$env:LOCALAPPDATA\Programs\7-Zip\7z.exe",
        "C:\Program Files\NVIDIA Corporation\NVIDIA GeForce Experience\7z.exe"
    )
    foreach ($path in $paths) {
        if ($path -and (Test-Path -LiteralPath $path -PathType Leaf)) {
            return $path
        }
    }
    return $null
}

$seven = Find-SevenZip $SevenZip
if (-not $seven) {
    throw "7-Zip not found. Install it, or pass -SevenZip <path to 7z.exe>."
}
Write-Host "7-Zip: $seven"

$archive = Join-Path $outPath "mangatl-portable-v$Version.7z"
Get-ChildItem -Path $outPath -Filter "mangatl-portable-v$Version.7z*" -File -ErrorAction SilentlyContinue |
    Remove-Item -Force

$folderName = Split-Path -Leaf $sourcePath
$parent = Split-Path -Parent $sourcePath
$archiveAbs = [System.IO.Path]::GetFullPath($archive)

Write-Host "Compressing $folderName -> $archiveAbs (volumes ${VolumeMB}m)"
Push-Location $parent
try {
    & $seven a -t7z -mx=5 -mmt=on "-v${VolumeMB}m" $archiveAbs $folderName
    if ($LASTEXITCODE -ne 0) {
        throw "7-Zip failed with exit code $LASTEXITCODE"
    }
}
finally {
    Pop-Location
}

$parts = Get-ChildItem -Path $outPath -Filter "mangatl-portable-v$Version.7z.*" -File |
    Where-Object { $_.Name -match '\.7z\.\d{3}$' } |
    Sort-Object Name
if (-not $parts) {
    throw "No archive produced. Did 7-Zip ignore -v${VolumeMB}m?"
}
if (@($parts).Count -eq 1 -and $parts[0].Name -like "*.001") {
    $single = Join-Path $outPath "mangatl-portable-v$Version.7z"
    Move-Item -LiteralPath $parts[0].FullName -Destination $single -Force
    $parts = @(Get-Item -LiteralPath $single)
}

$limit = 2000000000
$hashes = foreach ($part in $parts) {
    if ($part.Length -ge $limit) {
        Write-Warning "$($part.Name) is $($part.Length) bytes; GitHub may reject assets >= 2 GB."
    }
    $hash = (Get-FileHash -LiteralPath $part.FullName -Algorithm SHA256).Hash.ToLowerInvariant()
    Write-Host ("{0,8:N2} GB  {1}  {2}" -f ($part.Length / 1GB), $hash, $part.Name)
    "$hash  $($part.Name)"
}
$hashes | Set-Content -LiteralPath (Join-Path $outPath "SHA256SUMS.txt") -Encoding ascii

Write-Host ""
Write-Host "Release assets in $outPath"
Get-ChildItem -Path $outPath -File | Select-Object Name, @{n = "SizeGB"; e = { [math]::Round($_.Length / 1GB, 2) } } |
    Format-Table -AutoSize
Write-Host "SHA256SUMS.txt written."
