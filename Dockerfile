FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 TZ=America/Tegucigalpa
WORKDIR /app

RUN apt-get update \
 && apt-get install -y --no-install-recommends tzdata postgresql-client \
 && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .
RUN DJANGO_SECRET_KEY=build-only python manage.py collectstatic --noinput \
 && useradd --create-home caune && chown -R caune /app
USER caune

EXPOSE 8000
CMD ["sh", "-c", "python manage.py migrate --noinput && python manage.py inicializar_caune && gunicorn config.wsgi:application --bind 0.0.0.0:8000 --workers 3 --access-logfile -"]
