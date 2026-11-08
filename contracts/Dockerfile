# syntax=docker/dockerfile:1
FROM node:22-bookworm-slim AS node
FROM python:3.12-slim-bookworm
RUN apt-get update && apt-get install -y --no-install-recommends libstdc++6 ca-certificates \
    && rm -rf /var/lib/apt/lists/*
COPY --from=node /usr/local/bin/node /usr/local/bin/node
COPY --from=node /usr/local/lib/node_modules/npm /usr/local/lib/node_modules/npm
RUN ln -s ../lib/node_modules/npm/bin/npm-cli.js /usr/local/bin/npm
WORKDIR /workspace
COPY package.json package-lock.json ./
# The consumer imports the HTTP client only; no native SQLite addon is used.
RUN npm ci --ignore-scripts --no-audit --no-fund
COPY contracts/package.json contracts/package-lock.json ./contracts/
RUN cd contracts && npm ci --no-audit --no-fund
COPY services/notifications/requirements.txt ./services/notifications/requirements.txt
RUN python -m pip install --no-cache-dir -r services/notifications/requirements.txt
COPY lib ./lib
COPY services/notifications/app ./services/notifications/app
COPY contracts ./contracts
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1
CMD ["sh", "-c", "node contracts/consumer.mjs && node contracts/provider.mjs"]
