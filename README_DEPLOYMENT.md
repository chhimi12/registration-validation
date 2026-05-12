# Deployment

This app is now set up to deploy as a containerized FastAPI service that serves both the scanner UI and the `/scan` API.

## Local Run

```bash
pip install -r requirements.txt
uvicorn app:app --host 0.0.0.0 --port 8000
```

Open `http://127.0.0.1:8000`.

## Docker Run

```bash
docker build -t registration-validation .
docker run --rm -p 8000:8000 registration-validation
```

## Production Environment Variables

| Variable | Default | Purpose |
| --- | --- | --- |
| `PORT` | `8000` | HTTP port used by Uvicorn |
| `ALLOWED_ORIGINS` | `*` | Comma-separated CORS origins |
| `MAX_CONCURRENT_SCANS` | `2` | Limits simultaneous Chrome scans |
| `SCAN_TIMEOUT_SECONDS` | `90` | API timeout per scan |
| `PAGE_LOAD_TIMEOUT_SECONDS` | `45` | Selenium page-load timeout |
| `SELENIUM_WAIT_SECONDS` | `10` | Selenium explicit wait timeout |
| `PAGE_SETTLE_SECONDS` | `4` | Extra wait after page navigation |
| `IFRAME_SETTLE_SECONDS` | `1` | Extra wait after iframe navigation |
| `MIN_FORM_SCORE` | `2` | Minimum contact-form score |
| `CHROME_BINARY` | `/usr/bin/chromium` in Docker | Chrome/Chromium binary path |
| `CHROMEDRIVER_PATH` | `/usr/bin/chromedriver` in Docker | ChromeDriver path |
| `LOG_LEVEL` | `INFO` | Python logging level |

For a public deployment, set `ALLOWED_ORIGINS` to the deployed frontend origin instead of `*`.
