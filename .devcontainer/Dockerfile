FROM mcr.microsoft.com/vscode/devcontainers/python:3
ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1
WORKDIR /workspaces
COPY requirements.txt . 
RUN apt-get update && \
    apt-get install -y gcc libpq-dev \
    libcairo2 libcairo2-dev libpangocairo-1.0-0 weasyprint && \
    apt clean && \
    rm -rf /var/cache/apt/*
RUN python -m pip install -r requirements.txt 
RUN sanic server:app
USER vscode