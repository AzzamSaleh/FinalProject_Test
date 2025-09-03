FROM python:3.11-slim

# Install Chromium & Chromedriver for Selenium
RUN apt-get update && apt-get install -y --no-install-recommends \
    chromium chromium-driver fonts-liberation wget gnupg ca-certificates \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Python deps
COPY requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt

# App files
COPY . .

# Environment for headless Chrome + tidy logs
ENV PORT=8000
ENV HEADLESS=1
ENV PYTHONUNBUFFERED=1
ENV CHROME_BIN=/usr/bin/chromium
ENV CHROMEDRIVER_PATH=/usr/bin/chromedriver

# Start server with Gunicorn
CMD ["gunicorn", "app:app", "--bind", "0.0.0.0:8000", "--workers", "2", "--timeout", "120"]
