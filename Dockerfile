FROM python:3.12-slim
ENV PYTHONUNBUFFERED=1 PIP_NO_CACHE_DIR=1 DATABASE_PATH=/app/data/dating.sqlite3
WORKDIR /app
COPY . /app
# Optional wheelhouse permits verified downloads on the host and offline builds
# in environments whose Docker network has no DNS/proxy access.
RUN if [ -d /app/wheelhouse ]; then \
      python -m pip install --no-index --find-links=/app/wheelhouse 'setuptools==80.9.0' 'wheel==0.45.1' \
      && python -m pip install --no-index --find-links=/app/wheelhouse -r requirements.lock \
      && python -m pip install --no-deps --no-build-isolation .; \
    else \
      python -m pip install -r requirements.lock \
      && python -m pip install --no-deps .; \
    fi \
    && rm -rf /app/wheelhouse \
    && useradd --uid 10001 --create-home bot \
    && mkdir -p /app/data \
    && chown bot:bot /app/data
USER bot
CMD ["python", "-m", "dating"]
