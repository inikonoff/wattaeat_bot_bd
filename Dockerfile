FROM python:3.10-slim

# Устанавливаем системные зависимости
# libmagic1 - нужен для python-magic (определение типа файлов)
# ffmpeg - для конвертации голосовых
# curl - для скачивания шрифтов (на всякий случай)
RUN apt-get update && \
    apt-get install -y ffmpeg libmagic1 curl && \
    rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

# Создаем папки
RUN mkdir -p temp fonts

CMD ["python", "main.py"]
