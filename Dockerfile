# 1. Usar imagen base ligera de Python 3.11
FROM public.ecr.aws/docker/library/python:3.11-slim

# 2. Evitar generación de bytecode y forzar stdout sin búfer
ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1

# 3. Establecer directorio de trabajo
WORKDIR /app

# 4. Bibliotecas nativas requeridas por LightGBM y los componentes GIS
RUN apt-get update \
    && apt-get install -y --no-install-recommends libgomp1 libexpat1 \
    && rm -rf /var/lib/apt/lists/*

# 5. Copiar e instalar dependencias de Python
COPY requirements.txt ./

RUN pip install --no-cache-dir --upgrade pip \
    && pip install --no-cache-dir -r requirements.txt

# 6. Copiar el proyecto completo
COPY . .

# 7. Documentar el puerto utilizado localmente
EXPOSE 5000

# 8. Iniciar Gunicorn
# Railway proporciona la variable PORT; localmente utiliza 5000 como valor predeterminado
CMD ["sh", "-c", "exec gunicorn --bind 0.0.0.0:${PORT:-5000} --workers ${WEB_CONCURRENCY:-1} --threads ${GUNICORN_THREADS:-2} --timeout ${GUNICORN_TIMEOUT:-3600} --access-logfile - --error-logfile - app:app"]
