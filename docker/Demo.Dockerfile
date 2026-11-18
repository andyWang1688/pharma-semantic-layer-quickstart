# 可选客户端的独立运行环境，不依赖真实项目的 Python 或业务镜像。
FROM python:3.12-slim
COPY cube/requirements.txt /requirements.txt
COPY docker/requirements-dev.txt /requirements-dev.txt
RUN python -m venv /opt/venv && /opt/venv/bin/pip install --no-cache-dir -r /requirements.txt -r /requirements-dev.txt
# 使用虚拟环境；源码只读挂载，不在交付目录生成 pyc 缓存。
ENV PATH=/opt/venv/bin:$PATH PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=/example/cube:/example/demo
WORKDIR /example
CMD ["python", "/example/demo/app.py"]
