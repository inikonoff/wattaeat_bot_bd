# 1. Берем базовый образ Python
FROM python:3.10-slim

# 2. Устанавливаем системные зависимости
# ffmpeg - для конвертации аудио
# python3-dev, build-essential - иногда нужны для сборки библиотек
RUN apt-get update && \
    apt-get install -y ffmpeg build-essential && \
    rm -rf /var/lib/apt/lists/*

# 3. Настраиваем рабочую папку
WORKDIR /app

# 4. Копируем requirements и ставим библиотеки
COPY requirements.txt .
# Убираем PyAudio из установки, если он там остался, так как для Render он не нужен
RUN pip install --no-cache-dir -r requirements.txt

# 5. Копируем весь код
COPY . .

# 6. Создаем папку для временных файлов
RUN mkdir -p temp

# 7. Запускаем
CMD ["python", "main.py"]
