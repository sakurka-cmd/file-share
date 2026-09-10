FROM python:3.12-slim
WORKDIR /app
RUN mkdir -p /data
COPY app.py .
ENV HOST=0.0.0.0 PORT=8081 UPLOAD_DIR=/data
EXPOSE 8081
CMD ["python3", "app.py"]
