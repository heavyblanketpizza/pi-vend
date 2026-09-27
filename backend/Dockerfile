FROM python:3.11-slim

ENV PYTHONUNBUFFERED=1 \
    UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy \
    PLAYWRIGHT_BROWSERS_PATH=/ms-playwright

COPY --from=ghcr.io/astral-sh/uv:0.8 /uv /uvx /bin/

# Korean fonts so detail pages render even when the Pretendard CDN is unreachable.
RUN apt-get update \
    && apt-get install -y --no-install-recommends fonts-noto-cjk \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app
COPY pyproject.toml uv.lock ./
RUN uv sync --frozen --no-dev --no-install-project
ENV PATH="/app/.venv/bin:$PATH"
RUN playwright install --with-deps chromium

COPY . .
RUN DJANGO_SECRET_KEY=collectstatic python manage.py collectstatic --noinput

EXPOSE 8000
# gthread workers keep SSE chat streams from blocking other requests.
CMD ["sh", "-c", "python manage.py migrate --noinput && gunicorn config.wsgi --bind 0.0.0.0:8000 --worker-class gthread --workers 2 --threads 8 --timeout 600"]
