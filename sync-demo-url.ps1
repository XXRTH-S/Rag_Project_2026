# Check the active tunnel; use -Apply to sync and deploy the production frontend.
[CmdletBinding()]
param([switch]$Apply)
$ErrorActionPreference = 'Stop'
$projectRoot = $PSScriptRoot
$frontend = 'https://rag-project-2026.vercel.app'
$composeArgs = @('compose', '--project-directory', $projectRoot)
foreach ($name in @('docker-compose.yml', 'docker-compose.local.yml', 'docker-compose.override.yml', 'docker-compose.https.yml')) {
    $composeArgs += @('-f', (Join-Path $projectRoot $name))
}

function Test-DemoEndpoint([string]$Origin, [string]$Path, [int]$ExpectedStatus) {
    Add-Type -AssemblyName System.Net.Http
    $handler = New-Object System.Net.Http.HttpClientHandler
    $handler.AllowAutoRedirect = $false
    $client = New-Object System.Net.Http.HttpClient($handler)
    $client.Timeout = [TimeSpan]::FromSeconds(25)
    $client.DefaultRequestHeaders.Add('ngrok-skip-browser-warning', '1')
    try {
        $response = $client.GetAsync("$Origin$Path").GetAwaiter().GetResult()
        try {
            if ([int]$response.StatusCode -ne $ExpectedStatus) {
                throw "Unexpected HTTP $([int]$response.StatusCode) at $Path; expected $ExpectedStatus."
            }
            if ($response.Content.Headers.ContentType.MediaType -ne 'application/json') {
                throw "Expected JSON at $Path. The response may be an interstitial or frontend error."
            }
            $payload = $response.Content.ReadAsStringAsync().GetAwaiter().GetResult() | ConvertFrom-Json
            if ($Path -eq '/health' -and $payload.status -ne 'ok') { throw 'Backend health is not ok.' }
            if ($Path -eq '/api/auth/me' -and -not $payload.detail) { throw 'Invalid authentication response.' }
        } finally { $response.Dispose() }
    } finally { $client.Dispose(); $handler.Dispose() }
}

# Query the internal ngrok inspector without exposing the agent token or request data.
$probe = 'import json,urllib.request; d=json.load(urllib.request.urlopen("http://ngrok:4040/api/tunnels",timeout=10)); print(json.dumps([t["public_url"] for t in d["tunnels"] if t["public_url"].startswith("https://")]))'
$raw = $probe | & docker @composeArgs exec -T api python -
if ($LASTEXITCODE -ne 0) { throw 'Cannot read the tunnel. Start Docker and the HTTPS demo services first.' }
$origins = @((($raw -join "`n") | ConvertFrom-Json) | Select-Object -Unique)
if ($origins.Count -ne 1) { throw 'Expected exactly one active HTTPS tunnel; no deployment performed.' }
$uri = [Uri]$origins[0]
if (-not $uri.IsAbsoluteUri -or $uri.Scheme -ne 'https' -or $uri.UserInfo -or $uri.Query -or $uri.Fragment -or $uri.AbsolutePath -ne '/') {
    throw 'Tunnel URL must be an HTTPS origin without credentials, path, query or fragment.'
}
$origin = $uri.GetLeftPart([UriPartial]::Authority)
Test-DemoEndpoint $origin '/health' 200
Test-DemoEndpoint $origin '/api/auth/me' 401
Write-Host "Backend ready: $origin"
if (-not $Apply) {
    Test-DemoEndpoint $frontend '/health' 200
    Test-DemoEndpoint $frontend '/api/auth/me' 401
    Write-Host 'Production proxy responds correctly. No settings changed. This does not test model readiness or login credentials.'
    exit 0
}

$previousProject = $env:VERCEL_PROJECT_ID
$previousOrg = $env:VERCEL_ORG_ID
try {
    $link = Get-Content (Join-Path $projectRoot 'web/.vercel/project.json') -Raw | ConvertFrom-Json
    if ($link.projectId -ne 'prj_4cqCBJjVFg9I7EAW0qr2otkUy1HJ') { throw 'Unexpected Vercel project; stopping.' }
    $env:VERCEL_PROJECT_ID = $link.projectId
    $env:VERCEL_ORG_ID = $link.orgId
    $origin | & npx vercel env add BACKEND_HTTPS_ORIGIN production --cwd (Join-Path $projectRoot 'web') --force
    if ($LASTEXITCODE -ne 0) { throw 'Vercel environment update failed; deployment skipped.' }
    & npx vercel --cwd $projectRoot --local-config (Join-Path $projectRoot 'web/vercel.json') --prod --yes
    if ($LASTEXITCODE -ne 0) { throw 'Deployment failed. The saved origin changed; rerun -Apply after fixing the build.' }
    Test-DemoEndpoint $frontend '/health' 200
    Test-DemoEndpoint $frontend '/api/auth/me' 401
    Write-Host 'Production deployment and API proxy checks passed.'
} finally {
    $env:VERCEL_PROJECT_ID = $previousProject
    $env:VERCEL_ORG_ID = $previousOrg
}
