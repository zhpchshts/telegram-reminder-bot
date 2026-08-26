FROM python:3.14.7-slim-trixie

ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1
ENV PYTHONTZPATH=""

WORKDIR /app

COPY requirements.txt .

RUN python -m pip install --no-cache-dir --upgrade pip==26.2.1 \
    && python -m pip install --no-cache-dir -r requirements.txt

COPY pyproject.toml Dockerfile docker-compose.yml ./
COPY app ./app
COPY tma ./tma
COPY tests ./tests
COPY scripts ./scripts

CMD ["python", "-m", "app.main_with_api"]
