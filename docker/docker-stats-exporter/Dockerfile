FROM python:3.12.8-slim-bookworm
WORKDIR /app
COPY exporter.py /app/exporter.py
ENV LISTEN=0.0.0.0:9101 SCRAPE_INTERVAL=5
EXPOSE 9101
CMD ["python", "-u", "/app/exporter.py"]
