# Network Utilization Automation

Infrastructure automation tool for collecting monitoring metrics, validating utilization thresholds, and generating automated operational reports.

## Features

- Monitoring API integration
- Automated report generation
- Screenshot collection
- Config-driven execution
- Excel export

## Stack

- Python
- Requests
- Selenium
- OpenPyXL
- Automation

## Architecture

input
↓
data collection
↓
validation
↓
report generation
↓
excel / output

## Setup

```bash
pip install -r requirements.txt
```

Create .env from .env.example

Run:

```bash
python src/main.py
```
