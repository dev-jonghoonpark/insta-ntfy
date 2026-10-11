FROM python:3.13-slim
WORKDIR /app
# slim 이미지에는 시간대 데이터가 없어 Asia/Seoul을 쓰려면 필요하다.
RUN pip install --no-cache-dir tzdata
COPY insta_ntfy.py .
ENV PYTHONUNBUFFERED=1 STATE_FILE=/data/state.json
VOLUME /data
CMD ["python", "insta_ntfy.py"]
