param(
    [string]$BaseUrl = "http://127.0.0.1:8010"
)

$ErrorActionPreference = "Stop"
$base = $BaseUrl.TrimEnd("/")
$results = [System.Collections.Generic.List[object]]::new()

function Add-CheckResult {
    param(
        [string]$Name,
        [bool]$Ok,
        [string]$Detail,
        [ValidateSet("required", "optional")]
        [string]$Requirement = "required"
    )
    $results.Add([ordered]@{
        name = $Name
        ok = $Ok
        requirement = $Requirement
        detail = $Detail
    })
}

function Invoke-JsonGetCheck {
    param(
        [string]$Name,
        [string]$Path,
        [scriptblock]$Validate
    )
    try {
        $response = Invoke-RestMethod -Uri "$base$Path" -Method Get -TimeoutSec 30
        $validation = & $Validate $response
        Add-CheckResult -Name $Name -Ok ([bool]$validation.ok) -Detail ([string]$validation.detail)
    }
    catch {
        Add-CheckResult -Name $Name -Ok $false -Detail $_.Exception.Message
    }
}

Invoke-JsonGetCheck -Name "health/live" -Path "/health/live" -Validate {
    param($response)
    @{ ok = $response.status -in @("alive", "ok"); detail = "status=$($response.status)" }
}
Invoke-JsonGetCheck -Name "health/ready" -Path "/health/ready" -Validate {
    param($response)
    @{
        ok = $response.status -eq "ready" -and $response.catalog_loaded
        detail = "status=$($response.status); catalog_loaded=$($response.catalog_loaded); vector_degraded=$($response.vector_search_degraded)"
    }
}
Invoke-JsonGetCheck -Name "health" -Path "/health" -Validate {
    param($response)
    @{
        ok = $response.status -eq "ok" -and -not [string]::IsNullOrWhiteSpace($response.retrieval_mode)
        detail = "status=$($response.status); retrieval_mode=$($response.retrieval_mode)"
    }
}
Invoke-JsonGetCheck -Name "catalog/C6001" -Path "/api/catalog" -Validate {
    param($response)
    $programs = @($response.programs | Where-Object { $_.program_code -eq "C6001" })
    @{
        ok = $programs.Count -eq 2 -and $response.official_document_count -gt 0
        detail = "variants=$($programs.Count); official_documents=$($response.official_document_count)"
    }
}

try {
    $frontend = Invoke-WebRequest -UseBasicParsing -Uri "$base/" -Method Get -TimeoutSec 30
    $frontendOk = (
        $frontend.StatusCode -eq 200 -and
        $frontend.Content.Contains("C6001 Planner Demo") -and
        $frontend.Content.Contains("/static/js/planner-page.js") -and
        $frontend.Content.Contains('id="evidenceGrid"')
    )
    Add-CheckResult -Name "frontend/demo-first" -Ok $frontendOk -Detail "status=$($frontend.StatusCode); planner_entry=$frontendOk"
}
catch {
    Add-CheckResult -Name "frontend/demo-first" -Ok $false -Detail $_.Exception.Message
}

try {
    $plannerRequest = @{
        program_variant_id = "MONASH-C6001-EL2"
        handbook_year = 2026
        study_stream = "Industry Experience"
        completed_courses = @("FIT5057")
        max_courses_per_semester = 4
        preserve_policy_flexibility = $true
        start_semester = "2026-S2"
    } | ConvertTo-Json
    $planner = Invoke-RestMethod `
        -Uri "$base/api/plans/generate" `
        -Method Post `
        -ContentType "application/json" `
        -Body $plannerRequest `
        -TimeoutSec 45
    $plans = @($planner.plans)
    $evidence = @($planner.evidence)
    $officialLinks = @($evidence | Where-Object { -not [string]::IsNullOrWhiteSpace($_.source_url) })
    $plannerOk = (
        $plans.Count -eq 3 -and
        $planner.validation.all_valid -and
        $evidence.Count -gt 0 -and
        $officialLinks.Count -gt 0
    )
    Add-CheckResult `
        -Name "planner/C6001" `
        -Ok $plannerOk `
        -Detail "plans=$($plans.Count); all_valid=$($planner.validation.all_valid); evidence=$($evidence.Count); official_links=$($officialLinks.Count)"
}
catch {
    Add-CheckResult -Name "planner/C6001" -Ok $false -Detail $_.Exception.Message
}

$requiredFailures = @($results | Where-Object { $_.requirement -eq "required" -and -not $_.ok })
$payload = [ordered]@{
    base_url = $base
    status = if ($requiredFailures.Count -eq 0) { "PASS" } else { "FAIL" }
    passed = @($results | Where-Object { $_.ok }).Count
    total = $results.Count
    checks = $results
}
$payload | ConvertTo-Json -Depth 6
if ($requiredFailures.Count -gt 0) {
    exit 1
}
