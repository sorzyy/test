# deno : runtime JavaScript exigé par yt-dlp pour YouTube
FROM denoland/deno:bin AS deno

FROM python:3.12-slim

RUN apt-get update \
 && apt-get install -y --no-install-recommends ffmpeg ca-certificates tini \
 && rm -rf /var/lib/apt/lists/*
COPY --from=deno /deno /usr/local/bin/deno

ENV PATH=/opt/venv/bin:$PATH \
    PYTHONUNBUFFERED=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    TEMP_DIR=/tmp/saphir \
    PORT=9000

RUN useradd --create-home --uid 1000 saphir \
 && python -m venv /opt/venv

WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt \
 && chown -R saphir:saphir /opt/venv
COPY app ./app

# le venv appartient à l'utilisateur : la mise à jour auto de yt-dlp marche sans root
USER saphir
EXPOSE 9000
HEALTHCHECK --interval=60s --timeout=5s --start-period=20s \
  CMD python -c "import urllib.request,os;urllib.request.urlopen(f'http://127.0.0.1:{os.environ.get(\"PORT\",\"9000\")}/api/status', timeout=4)"
ENTRYPOINT ["tini", "--"]
CMD ["sh", "-c", "exec uvicorn app.main:app --host 0.0.0.0 --port ${PORT} --proxy-headers --forwarded-allow-ips='*'"]
