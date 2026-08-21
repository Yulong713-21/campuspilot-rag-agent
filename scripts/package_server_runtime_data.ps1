param(
    [string]$OutputDirectory = "deploy\production\runtime-data",
    [string]$EmbeddingModelPath = "D:\agentdev\models\all-MiniLM-L6-v2",
    [string]$RerankerModelPath = "D:\agentdev\models\ms-marco-MiniLM-L6-v2",
    [switch]$IncludeModel
)

$ErrorActionPreference = "Stop"
$repoRoot = Split-Path -Parent $PSScriptRoot
$outputRoot = Join-Path $repoRoot $OutputDirectory
$sourceRoot = Join-Path $repoRoot "data\official_sources"
$targetSources = Join-Path $outputRoot "official_sources"

$required = @(
    "extraction-report.json",
    "handbook-chunks.jsonl"
)
foreach ($name in $required) {
    $path = Join-Path $sourceRoot $name
    if (-not (Test-Path -LiteralPath $path)) {
        throw "Missing runtime data file: $path"
    }
}

New-Item -ItemType Directory -Force -Path $targetSources | Out-Null
Copy-Item -LiteralPath (Join-Path $sourceRoot "extraction-report.json") -Destination $targetSources -Force
Copy-Item -LiteralPath (Join-Path $sourceRoot "handbook-chunks.jsonl") -Destination $targetSources -Force

$cleanSource = Join-Path $sourceRoot "clean"
if (Test-Path -LiteralPath $cleanSource) {
    Copy-Item -LiteralPath $cleanSource -Destination $targetSources -Recurse -Force
}

if ($IncludeModel) {
    if (-not (Test-Path -LiteralPath $EmbeddingModelPath)) {
        throw "Embedding model not found: $EmbeddingModelPath"
    }
    $modelTarget = Join-Path $outputRoot "models\all-MiniLM-L6-v2"
    New-Item -ItemType Directory -Force -Path (Split-Path -Parent $modelTarget) | Out-Null
    Copy-Item -LiteralPath $EmbeddingModelPath -Destination $modelTarget -Recurse -Force

    if (-not (Test-Path -LiteralPath $RerankerModelPath)) {
        throw "Reranker model not found: $RerankerModelPath"
    }
    $rerankerTarget = Join-Path $outputRoot "models\ms-marco-MiniLM-L6-v2"
    Copy-Item -LiteralPath $RerankerModelPath -Destination $rerankerTarget -Recurse -Force
}

$chunks = Join-Path $targetSources "handbook-chunks.jsonl"
$manifest = [ordered]@{
    generated_at = (Get-Date).ToUniversalTime().ToString("o")
    handbook_chunks_sha256 = (Get-FileHash -Algorithm SHA256 -LiteralPath $chunks).Hash.ToLowerInvariant()
    handbook_chunks_bytes = (Get-Item -LiteralPath $chunks).Length
    includes_clean_sources = (Test-Path -LiteralPath (Join-Path $targetSources "clean"))
    includes_embedding_model = $IncludeModel.IsPresent
    includes_reranker_model = $IncludeModel.IsPresent
}
$manifest | ConvertTo-Json | Set-Content -LiteralPath (Join-Path $outputRoot "runtime-manifest.json") -Encoding UTF8
$manifest | ConvertTo-Json
