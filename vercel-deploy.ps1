# Explicit deployment command; credentials are never copied to Vercel.
$env:VERCEL_PROJECT_ID = "prj_4cqCBJjVFg9I7EAW0qr2otkUy1HJ"
$vercelLink = Get-Content "$PSScriptRoot/web/.vercel/project.json" -Raw | ConvertFrom-Json
$env:VERCEL_ORG_ID = $vercelLink.orgId
& npx vercel --cwd "$PSScriptRoot/web" @args
exit $LASTEXITCODE
