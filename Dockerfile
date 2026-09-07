FROM python:3.13-slim

WORKDIR /app

ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1

# System dependencies
RUN apt-get update && apt-get install -y \
    gcc \
    libpq-dev \
    libssl-dev \
    libffi-dev \
    python3-dev \
    build-essential \
    && rm -rf /var/lib/apt/lists/*

# Install Python dependencies
COPY requirements.txt /app/

RUN pip install --upgrade pip
RUN pip install --no-cache-dir -r requirements.txt

# Copy project
COPY . /app/

# Ensure folders exist
RUN mkdir -p /app/media /app/staticfiles

CMD ["sh", "-c", "python manage.py collectstatic --noinput && python manage.py migrate && daphne -b 0.0.0.0 -p 8012 crescent_pharma.asgi:application"]