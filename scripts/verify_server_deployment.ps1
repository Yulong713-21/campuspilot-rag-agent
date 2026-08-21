param(
    [string]$BaseUrl = "http://127.0.0.1:8010"
)

$ErrorActionPreference = "Stop"
$checks = @(
    @{ name = "live"; url = "$BaseUrl/health/live" },
    @{ name = "ready"; url = "$BaseUrl/health/ready" },
    @{ name = "health"; url = "$BaseUrl/health" },
    @{ name = "monash_business"; url = "$BaseUrl/api/admissions/programs?university=Monash&discipline_id=business" },
    @{ name = "monash_computing"; url = "$BaseUrl/api/admissions/programs?university=Monash&discipline_id=computing" }
)

$results = foreach ($check in $checks) {
    try {
        $response = Invoke-RestMethod -Uri $check.url -Method Get -TimeoutSec 30
        $itemCount = if ($null -ne $response.count) {
            $response.count
        }
        elseif ($null -ne $response.programs) {
            @($response.programs).Count
        }
        else {
            $null
        }
        [ordered]@{
            name = $check.name
            ok = $true
            status = $response.status
            count = $itemCount
            retrieval_mode = $response.retrieval_mode
        }
    }
    catch {
        [ordered]@{
            name = $check.name
            ok = $false
            error = $_.Exception.Message
        }
    }
}

$payload = [ordered]@{
    base_url = $BaseUrl
    passed = @($results | Where-Object { $_.ok }).Count
    total = @($results).Count
    checks = $results
}
$payload | ConvertTo-Json -Depth 5
if ($payload.passed -ne $payload.total) {
    exit 1
}
