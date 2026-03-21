FROM python:3.12-slim-bookworm

WORKDIR /app
ENV PYTHONPATH=/app

# Install system deps + Playwright browser dependencies
RUN apt-get update && apt-get install -y --no-install-recommends \
    libpq-dev \
    # Playwright Chromium dependencies
    libnss3 libnspr4 libatk1.0-0 libatk-bridge2.0-0 libcups2 libdbus-1-3 \
    libdrm2 libxkbcommon0 libatspi2.0-0 libxcomposite1 libxdamage1 \
    libxfixes3 libxrandr2 libgbm1 libpango-1.0-0 libcairo2 libasound2 \
    fonts-liberation fonts-noto-color-emoji fonts-unifont \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Install Playwright Chromium (without --with-deps, deps already installed above)
RUN playwright install chromium

COPY . .

CMD ["python", "-m", "src.main"]
