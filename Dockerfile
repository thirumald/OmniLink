# One Python image for connectors, services, workflow workers and the assistant; the command selects the role.
FROM python:3.12-slim AS base
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 \
    PYTHONPATH=/app/libs/omnilink_contracts:/app/libs/omnilink_sdk:/app/services:/app/connectors:/app/edge:/app/workflow/temporal:/app/assistant:/app
WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY libs libs
COPY services services
COPY connectors connectors
COPY edge edge
COPY processing processing
COPY workflow/temporal workflow/temporal
COPY assistant assistant
RUN useradd -u 10001 -m omnilink && mkdir -p /var/lib/omnilink && chown omnilink /var/lib/omnilink
USER 10001
# examples:
#   connector:   python -m omnilink_sdk.runner --config /etc/omnilink/connector.yaml
#   service:     uvicorn --factory omnilink_services.alarms:build_app --host 0.0.0.0 --port 8002
#   assistant:   uvicorn --factory omnilink_assistant.app:build_app --host 0.0.0.0 --port 8020
CMD ["python", "-c", "print('choose a command, see Dockerfile comments')"]
