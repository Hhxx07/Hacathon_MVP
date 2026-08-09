FROM python:3.12-slim AS runtime
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 PIP_NO_CACHE_DIR=1
RUN groupadd --system app && useradd --system --gid app --home /app app
WORKDIR /app
COPY pyproject.toml ./
COPY services ./services
RUN pip install .
COPY alembic.ini ./
COPY migrations ./migrations
USER app
EXPOSE 8000
CMD ["uvicorn", "services.core.app.main:app", "--host", "0.0.0.0", "--port", "8000"]
