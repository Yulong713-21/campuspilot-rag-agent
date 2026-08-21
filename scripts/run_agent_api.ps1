param(
    [string]$BindHost = "127.0.0.1",
    [int]$Port = 8010,
    [switch]$EnableVectorSearch,
    [switch]$EnableLlm,
    [string]$OllamaUrl = "http://127.0.0.1:11434",
    [string]$OllamaModel = "qwen3.5:2b-q4_K_M",
    [string]$MilvusUri = "http://192.168.150.101:19530",
    [string]$MilvusCollection = "campuspilot_handbook_v2",
    [string]$EmbeddingBackend = "sentence-transformer",
    [string]$EmbeddingModelPath = "D:\agentdev\models\all-MiniLM-L6-v2"
)

$repoRoot = Split-Path -Parent $PSScriptRoot
$python = Join-Path $repoRoot ".venv\Scripts\python.exe"
$envFile = Join-Path $repoRoot ".env"

if (-not (Test-Path -LiteralPath $python)) {
    throw "Python virtual environment not found: $python"
}

if (Test-Path -LiteralPath $envFile) {
    foreach ($line in Get-Content -LiteralPath $envFile -Encoding UTF8) {
        $trimmed = $line.Trim()
        if (-not $trimmed -or $trimmed.StartsWith("#")) {
            continue
        }
        $name, $value = $trimmed.Split("=", 2)
        if ($name -and $null -ne $value) {
            Set-Item -Path "Env:$($name.Trim())" -Value $value.Trim()
        }
    }
}

Push-Location $repoRoot
try {
    if ($EnableVectorSearch) {
        $env:CAMPUSPILOT_VECTOR_SEARCH_ENABLED = "1"
        $env:CAMPUSPILOT_MILVUS_URI = $MilvusUri
        $env:CAMPUSPILOT_MILVUS_COLLECTION = $MilvusCollection
        $env:CAMPUSPILOT_EMBEDDING_BACKEND = $EmbeddingBackend
        $env:CAMPUSPILOT_EMBEDDING_MODEL_PATH = $EmbeddingModelPath
    }
    if ($EnableLlm) {
        $env:CAMPUSPILOT_LLM_ENABLED = "1"
        $env:CAMPUSPILOT_OLLAMA_URL = $OllamaUrl
        $env:CAMPUSPILOT_OLLAMA_MODEL = $OllamaModel
    }
    & $python -m uvicorn agent_runtime.api:app `
        --app-dir (Join-Path $repoRoot "src") `
        --host $BindHost `
        --port $Port
}
finally {
    Pop-Location
}
