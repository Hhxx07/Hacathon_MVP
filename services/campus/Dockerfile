FROM python:3.12-slim
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1
RUN groupadd --system app && useradd --system --gid app --home /app app
WORKDIR /app
RUN pip install --no-cache-dir "fastapi>=0.115,<1" "uvicorn>=0.30,<1" "pydantic>=2.9,<3"
COPY services ./services
USER app
EXPOSE 8010
CMD ["uvicorn", "services.campus.campus.main:app", "--host", "0.0.0.0", "--port", "8010"]

