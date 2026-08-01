FROM python:3.10-slim

# Installation de FFmpeg et Zip au niveau du système Linux de Render
RUN apt-get update && \
    apt-get install -y ffmpeg zip && \
    rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY "Convertisseur Vidéo.py" .

CMD ["python", "Convertisseur Vidéo.py"]
