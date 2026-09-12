FROM python:3.12-slim
WORKDIR /app
COPY requirements.lock ./requirements.lock
RUN pip install --no-cache-dir -r requirements.lock
COPY app ./app
RUN useradd --create-home museboard && mkdir -p /data && chown museboard:museboard /data
USER museboard
ENV STORAGE_DIR=/data
EXPOSE 8000
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
