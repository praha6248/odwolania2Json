FROM python:3.13-slim

ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 PIP_NO_CACHE_DIR=1 O2J_NO_UPDATE_CHECK=1

RUN apt-get update \
 && apt-get install -y --no-install-recommends tesseract-ocr tesseract-ocr-pol libgl1 libglib2.0-0 \
 && rm -rf /var/lib/apt/lists/*

WORKDIR /app
COPY requirements.txt .
RUN pip install -r requirements.txt

COPY odwolania2json ./odwolania2json
COPY config ./config
RUN mkdir -p input output

EXPOSE 8000
CMD ["python", "-m", "odwolania2json", "serve", "--host", "0.0.0.0", "--port", "8000"]
