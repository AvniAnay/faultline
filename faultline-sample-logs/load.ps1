# Loads sample-logs.ndjson into Elasticsearch (security disabled, plain HTTP). Windows PowerShell.
param(
  [string]$File  = "sample-logs.ndjson",
  [string]$EsUrl = "http://localhost:9200",
  [string]$Index = "logs-faultline"
)
Write-Host "Creating index $Index (ignore 'already exists' errors)..."
try {
  Invoke-RestMethod -Method Put -Uri "$EsUrl/$Index" -ContentType "application/json" -InFile "mapping.json" | Out-Null
} catch { Write-Host $_.Exception.Message }

Write-Host "Loading $File..."
$r = Invoke-RestMethod -Method Post -Uri "$EsUrl/$Index/_bulk?refresh=true" -ContentType "application/x-ndjson" -InFile $File
Write-Host "errors: $($r.errors)  items: $($r.items.Count)"

Write-Host "Document count:"
(Invoke-RestMethod -Uri "$EsUrl/$Index/_count").count
