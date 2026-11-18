# 独立转换任务：固定 dbt 版本，不依赖真实项目的 Dagster 镜像。
FROM python:3.12-slim
COPY dbt/requirements.txt /requirements.txt
RUN python -m venv /opt/venv && /opt/venv/bin/pip install --no-cache-dir -r /requirements.txt
ENV PATH=/opt/venv/bin:$PATH PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=/example/cube:/example/demo
WORKDIR /example/dbt
ENTRYPOINT ["dbt"]
CMD ["build", "--profiles-dir", "."]
