FROM python:3.12-slim

RUN apt-get update && apt-get install -y --no-install-recommends \
    curl bash \
    && curl -fsSL https://deb.nodesource.com/setup_22.x | bash - \
    && apt-get install -y --no-install-recommends nodejs \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY pyproject.toml .
COPY src/ src/
RUN pip install --no-cache-dir .

COPY web/vite-frontend/package*.json web/vite-frontend/
RUN cd web/vite-frontend && npm install

COPY . .

ENV PYTHONUNBUFFERED=1
EXPOSE 8000 8001 5173
CMD ["bash", "script/start_matcreator.sh"]
