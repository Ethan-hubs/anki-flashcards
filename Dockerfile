FROM python:3.12-slim

WORKDIR /app

# 安装依赖
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# 复制应用
COPY server.py ./
COPY scripts/ scripts/
COPY web/ web/
COPY deploy/ deploy/

# 数据目录（挂载卷）
VOLUME ["/app/data", "/app/raw"]

# 默认端口 8090（可用 FLASHCARD_PORT 覆盖）
EXPOSE 8090

# 健康检查
HEALTHCHECK --interval=30s --timeout=5s --retries=3 \
  CMD python3 -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8090/api/due')" || exit 1

CMD ["python3", "server.py"]
