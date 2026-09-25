FROM python:3.12.8-bookworm
WORKDIR /opt/mock
RUN pip install --no-cache-dir flask==3.0.3
COPY docker/payment-mock/server.py /opt/mock/server.py
EXPOSE 8090
HEALTHCHECK --interval=5s --timeout=3s --retries=10 CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8090/health')"
CMD ["python", "/opt/mock/server.py"]
