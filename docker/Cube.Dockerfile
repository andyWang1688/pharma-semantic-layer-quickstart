# 在虚拟环境中准备纯 Python 依赖，避免跨 Python 版本复制二进制数据库驱动。
FROM python:3.12-slim AS python_dependencies
COPY cube/requirements.txt /requirements.txt
RUN python -m venv /build-venv && /build-venv/bin/pip install --no-cache-dir --target /python-packages -r /requirements.txt

# 固定 Cube 版本，模型与 Python 钩子均在此版本验证。
FROM cubejs/cube:v1.7.1
COPY --from=python_dependencies /python-packages /opt/python-packages
# 允许原生 cube.py 导入数据库驱动及本例 security 包。
ENV PYTHONPATH=/opt/python-packages:/cube/conf
