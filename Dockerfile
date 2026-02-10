FROM python:3.10-slim-bullseye AS builder

ENV PYTHONUNBUFFERED=1

RUN apt-get update && apt-get install -y --no-install-recommends \
    libcairo2-dev \
    gcc \
    g++ \
    libpango1.0-dev \
    libgdk-pixbuf2.0-dev \
    libffi-dev \
    shared-mime-info \
    libmagic1 \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app/

COPY requirements.txt .
RUN pip install --upgrade pip && \
    pip install --no-cache-dir --prefix=/install -r requirements.txt

FROM python:3.10-slim-bullseye AS runtime

ENV PYTHONUNBUFFERED=1

RUN apt-get update && apt-get install -y --no-install-recommends \
    libcairo2 \
    libpango-1.0-0 \
    libpangocairo-1.0-0 \
    libgdk-pixbuf2.0-0 \
    libffi7 \
    shared-mime-info \
    libmagic1 \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app/

COPY --from=builder /install /usr/local

COPY . .

RUN chmod +x /app/entrypoint.sh

EXPOSE 8000

CMD ["sh", "./entrypoint.sh"]
