FROM python:3.12-slim
WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt && useradd -m -u 10001 risklatch && mkdir /app/data && chown risklatch /app/data
COPY . .
USER risklatch
EXPOSE 8000
CMD ["gunicorn","--bind","0.0.0.0:8000","--workers","2","app:app"]
