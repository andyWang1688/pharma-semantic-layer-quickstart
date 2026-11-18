"""示例的 PostgreSQL 访问：参数绑定、请求内一致性快照、超时与资源释放。"""

import os
from contextlib import contextmanager
from contextvars import ContextVar
from typing import Any

import pg8000.dbapi


class DemoError(Exception):
    """可向演示客户端解释的权限或输入错误；status 用于 HTTP 适配。"""

    def __init__(self, message: str, status: int = 403):
        super().__init__(message)
        self.status = status


_read_connection: ContextVar[Any] = ContextVar("read_connection", default=None)


def connect():
    """连接独立合成库；Compose 注入配置，调用者负责关闭连接。"""
    return pg8000.dbapi.connect(
        host=os.environ.get("PGHOST", "db"),
        port=int(os.environ.get("PGPORT", "5432")),
        database=os.environ.get("PGDATABASE", "shared_sales"),
        user=os.environ.get("PGUSER", "example"),
        password=os.environ.get("PGPASSWORD", "example-only"),
        timeout=10,
    )


@contextmanager
def read_session():
    """请求内复用只读 REPEATABLE READ 事务；嵌套调用共享同一连接。

    撤权在下一请求重新读取；已开始的请求按它读取的权限快照完成。
    此处没有跨请求权限缓存。生产连接池可替换 connect，事务语义保持一致。
    """
    if _read_connection.get() is not None:
        yield
        return
    connection = connect()
    token = _read_connection.set(connection)
    try:
        cursor = connection.cursor()
        try:
            cursor.execute("SET TRANSACTION ISOLATION LEVEL REPEATABLE READ READ ONLY")
            cursor.execute("SET LOCAL statement_timeout = '10s'")
        finally:
            cursor.close()
        yield
    finally:
        _read_connection.reset(token)
        try:
            connection.rollback()
        finally:
            connection.close()


def query(sql: str, parameters: tuple = ()) -> list[dict[str, Any]]:
    """绑定参数执行 SQL。权限入口处于只读事务；夹具写入使用独立事务。"""
    shared = _read_connection.get()
    connection = shared if shared is not None else connect()
    cursor = connection.cursor()
    try:
        if shared is None:
            cursor.execute("SET LOCAL statement_timeout = '10s'")
        cursor.execute(sql, parameters)
        columns = [column[0] for column in cursor.description] if cursor.description else []
        rows = [dict(zip(columns, row, strict=True)) for row in cursor.fetchall()] if columns else []
        if shared is None:
            connection.commit()
        return rows
    finally:
        try:
            cursor.close()
        finally:
            if shared is None:
                connection.close()
