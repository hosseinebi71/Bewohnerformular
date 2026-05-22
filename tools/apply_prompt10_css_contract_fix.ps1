$ErrorActionPreference = "Stop"
$projectRoot = Get-Location
$appCss = Join-Path $projectRoot "static\form_builder\app.css"
$snippet = Join-Path $projectRoot "static\form_builder\prompt10_css_contract_append.css"

if (!(Test-Path $appCss)) {
    throw "static\form_builder\app.css was not found. Run this from the Bewohnerformular project root."
}
if (!(Test-Path $snippet)) {
    throw "static\form_builder\prompt10_css_contract_append.css was not found. Copy the ZIP contents into the project root first."
}

$current = Get-Content $appCss -Raw
if ($current -notmatch "Prompt 10 correction: CSS contract definitions") {
    Add-Content -Path $appCss -Value "`r`n"
    Add-Content -Path $appCss -Value (Get-Content $snippet -Raw)
    Write-Host "Prompt 10 CSS contract fix appended to static\form_builder\app.css"
} else {
    Write-Host "Prompt 10 CSS contract fix is already present in static\form_builder\app.css"
}
