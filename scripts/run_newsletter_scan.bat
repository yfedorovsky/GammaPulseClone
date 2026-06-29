@echo off
REM Weekly Tier-1 AI-newsletter scan — saves digest + pushes to Telegram.
REM Scheduled via: schtasks "GammaPulse Newsletter Scan" (Mon 08:00).
cd /d C:\Dev\GammaPulse
if not exist logs mkdir logs
".venv\Scripts\python.exe" -m scripts.newsletter_scan --telegram >> logs\newsletter_scan.log 2>&1
