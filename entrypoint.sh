#!/bin/bash

echo "Waiting for database to be ready..."
python3 manage.py makemigrations
python3 manage.py migrate
python3 manage.py collectstatic --noinput
python3 manage.py createhorillauser --first_name admin --last_name admin --username admin --password admin --email admin@example.com --phone 1234567890 || true

# Use PORT from environment variable (Railway provides this), default to 8000
PORT=${PORT:-8000}
echo "Starting server on port $PORT..."
gunicorn --bind 0.0.0.0:$PORT horilla.wsgi:application
