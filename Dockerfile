# ==============================================================================
# Stage 1: Build dashboard (React + Vite)
# ==============================================================================
FROM node:22-slim AS dashboard-builder

WORKDIR /build
COPY dashboard/package.json dashboard/package-lock.json ./
RUN npm ci --no-audit --no-fund
COPY dashboard/ ./
RUN npm run build


# ==============================================================================
# Stage 2: Python runtime with Chromium + Xvfb
# ==============================================================================
FROM python:3.12-slim AS runtime

# Prevent interactive prompts and Python buffering
ENV DEBIAN_FRONTEND=noninteractive \
    PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1

# Install system dependencies for Chromium, Xvfb, and VNC
RUN apt-get update && apt-get install -y --no-install-recommends \
    # Xvfb virtual display
    xvfb \
    # VNC server for remote browser access (login/captcha)
    x11vnc \
    # Chromium dependencies (patchright/playwright needs these)
    libnss3 \
    libnspr4 \
    libatk1.0-0 \
    libatk-bridge2.0-0 \
    libcups2 \
    libdrm2 \
    libdbus-1-3 \
    libxkbcommon0 \
    libxcomposite1 \
    libxdamage1 \
    libxfixes3 \
    libxrandr2 \
    libgbm1 \
    libpango-1.0-0 \
    libcairo2 \
    libasound2 \
    libatspi2.0-0 \
    libwayland-client0 \
    # Fonts for proper text rendering
    fonts-liberation \
    fonts-noto-core \
    # Utilities
    curl \
    procps \
    && rm -rf /var/lib/apt/lists/*

# Create non-root user for running the bot
RUN groupadd -r staemme && useradd -r -g staemme -m -s /bin/bash staemme

WORKDIR /app

# Install build tool + dependencies (cached layer — only reruns when pyproject.toml changes)
COPY pyproject.toml ./
RUN pip install --no-cache-dir hatchling && \
    python -c "import tomllib; d=tomllib.loads(open('pyproject.toml').read()); print('\n'.join(d['project']['dependencies']))" \
    | pip install --no-cache-dir -r /dev/stdin

# Install websockify (noVNC websocket proxy) without numpy (avoids CPU compat issues)
# and download noVNC web client
RUN pip install --no-cache-dir websockify && \
    pip uninstall -y numpy 2>/dev/null; \
    curl -sL https://github.com/novnc/noVNC/archive/refs/tags/v1.5.0.tar.gz | tar xz -C /opt && \
    mv /opt/noVNC-1.5.0 /opt/novnc

# Install patchright Chromium browser
RUN patchright install chromium && \
    # Move browser to a shared location accessible by staemme user
    mkdir -p /home/staemme/.cache && \
    cp -r /root/.cache/ms-playwright /home/staemme/.cache/ms-playwright && \
    chown -R staemme:staemme /home/staemme/.cache

# Copy application source and install package (deps already cached above)
COPY src/ ./src/
COPY config/ ./config/
RUN pip install --no-cache-dir --no-deps .

# Copy dashboard build from stage 1
COPY --from=dashboard-builder /build/dist ./dashboard/dist

# Copy entrypoint
COPY docker/entrypoint.sh /entrypoint.sh
RUN chmod +x /entrypoint.sh

# Create data and logs directories with proper permissions
RUN mkdir -p /app/data /app/logs && \
    chown -R staemme:staemme /app

# Expose ports: API (8000), VNC (5900), noVNC (6080)
EXPOSE 8000 5900 6080

# Health check against API endpoint
HEALTHCHECK --interval=30s --timeout=5s --start-period=60s --retries=3 \
    CMD curl -f http://localhost:8000/api/health || exit 1

USER staemme

ENTRYPOINT ["/entrypoint.sh"]
