FROM python:3.12-alpine
WORKDIR /app
COPY backend/app/ ./app/
COPY algo/ ./algo/
ENV PYTHONPATH=/app:/app/app
EXPOSE 8000
CMD ["python", "app/main.py"]
