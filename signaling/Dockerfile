FROM python:3.12-slim
WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY pocketdesk_signaling ./pocketdesk_signaling
ENV HOST=0.0.0.0 PORT=8080 POCKETDESK_DB=/data/pocketdesk.db TRUST_PROXY=1
# Runs as root inside the container so a mounted volume (/data) is writable; the container itself is isolated.
RUN mkdir -p /data
VOLUME /data
CMD ["python", "-m", "pocketdesk_signaling.app"]
