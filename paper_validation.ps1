$OutputDir = "paper_validation_logs"
$Command = "python .\live_runner.py --watchlist .\trading_system\config\watchlist.txt --output-dir .\$OutputDir --dry-run --paper --max-loops 600"
Write-Host "Starting paper-trading validation run..."
Write-Host $Command
Invoke-Expression $Command
Write-Host ""
Write-Host "Review these files after the run:"
Write-Host ".\$OutputDir\trading.log"
Write-Host ".\$OutputDir\heartbeat.json"
Write-Host ".\$OutputDir\bars_$(Get-Date -Format 'yyyy-MM-dd').csv"
Write-Host ".\$OutputDir\signals_$(Get-Date -Format 'yyyy-MM-dd').csv"
