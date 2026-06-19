# Manual smoke test against local dev server (localhost is intentional)
Invoke-RestMethod -Uri "http://127.0.0.1:8787/query" -Method POST -ContentType "application/json" -Body '{"query": "What is CyClaw?"}' # DevSkim: ignore DS176209 DS137138
