# Usamos una versión más reciente para evitar el error de "Executable doesn't exist"
FROM mcr.microsoft.com/playwright/python:v1.49.0-jammy

ENV PYTHONUNBUFFERED=1

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Instalamos los navegadores que corresponden a esta versión
RUN playwright install chromium

COPY . .

CMD ["sh", "-c", "uvicorn main:app --host 0.0.0.0 --port ${PORT}"]
