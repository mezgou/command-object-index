FROM python:3.12-alpine
WORKDIR /app
COPY backend/requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt
COPY backend/app/ ./app/
COPY algo/ ./algo/
ENV PYTHONPATH=/app:/app/app
EXPOSE 8000
CMD ["python", "app/main.py"]
