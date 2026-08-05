# 1. Usar imagen base ligera de Python 3.11/3.13
FROM python:3.11-slim

# 2. Evitar generación de bytecode y forzar stdout sin búfer
ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1

# 3. Establecer directorio de trabajo en el contenedor
WORKDIR /app

# 4. Copiar e instalar dependencias
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# 5. Copiar todo el contenido del proyecto (código, carpetas de modelos, datasets)
COPY . .

# 6. Exponer el puerto en el que correrá Gunicorn
EXPOSE 5000

# 7. Comando de arranque usando Gunicorn (Production WSGI)
CMD ["gunicorn", "--bind", "0.0.0.0:5000", "--workers", "2", "--timeout", "120", "app:app"]
