FROM python:3.12-slim
WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY pocketdesk_signaling ./pocketdesk_signaling
ENV HOST=0.0.0.0 PORT=8080 POCKETDESK_DB=/data/pocketdesk.db TRUST_PROXY=1
VOLUME /data
USER nobody
CMD ["python", "-m", "pocketdesk_signaling.app"]
