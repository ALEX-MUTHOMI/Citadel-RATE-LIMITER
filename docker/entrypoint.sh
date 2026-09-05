#!/bin/sh
set -eu

python manage.py migrate --noinput
python manage.py bootstrap_client
python manage.py collectstatic --noinput

exec gunicorn citadel.wsgi:application --bind 0.0.0.0:8000 --workers 2
