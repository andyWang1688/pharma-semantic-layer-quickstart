import json
import logging
from datetime import date, datetime
from decimal import Decimal
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse

from diagnostics import run_sales_example
from security.database import DemoError
from tools import FUNCTIONS, TOOL_SCHEMAS

# 静态资源使用显式白名单，不接受任意文件路径；HTML、CSS、JS 分开便于评审。
STATIC_FILES = {
    "/": ("index.html", "text/html; charset=utf-8"),
    "/static/styles.css": ("styles.css", "text/css; charset=utf-8"),
    "/static/app.js": ("app.js", "text/javascript; charset=utf-8"),
}


def json_default(value):
    # 数据库 numeric/date 转成 JSON 值，方便浏览器展示。
    if isinstance(value, Decimal):
        return float(value)
    if isinstance(value, (date, datetime)):
        return value.isoformat()
    raise TypeError(f"Cannot serialize {type(value).__name__}")


LOGGER = logging.getLogger(__name__)
MAX_REQUEST_BYTES = 262144


class Handler(BaseHTTPRequestHandler):
    # 这个服务只承接本机页面和可选工具；Cube 不通过 HTTP 回调它做权限。
    def respond(self, status, value, content_type="application/json; charset=utf-8"):
        body = (
            value if isinstance(value, bytes) else json.dumps(value, ensure_ascii=False, default=json_default).encode()
        )
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Cache-Control", "no-store")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def dispatch(self):
        parsed = urlparse(self.path)
        if self.command == "GET" and parsed.path == "/health":
            return self.respond(200, {"ok": True})
        if self.command == "GET" and parsed.path in STATIC_FILES:
            filename, content_type = STATIC_FILES[parsed.path]
            return self.respond(200, (Path(__file__).parent / "static" / filename).read_bytes(), content_type)
        if self.command == "GET" and parsed.path == "/api/tool-schemas":
            return self.respond(200, TOOL_SCHEMAS)
        # 仅合成演示允许请求头切换身份；生产必须用已验证登录态，不能信任这个头。
        viewer_id = self.headers.get("X-Demo-Viewer", "M001")
        if self.command == "GET" and parsed.path == "/api/example":
            # 页面诊断接口额外执行原始对账等步骤，普通业务使用下方工具接口。
            parameters = parse_qs(parsed.query)

            def selected(name, default):
                return parameters.get(name, [default])[0]

            month = selected("month", "2026-01")
            return self.respond(
                200,
                run_sales_example(
                    viewer_id,
                    selected("employee", "M001").split(","),
                    ["2026-01", "2026-02"] if month == "all" else [month],
                    selected("mode", "current"),
                    selected("snapshot", None),
                    selected("view", "detail"),
                    hospital_codes=selected("hospitals", "").split(",") if selected("hospitals", "") else None,
                    product_codes=selected("products", "").split(",") if selected("products", "") else None,
                ),
            )
        if self.command == "POST":
            length = int(self.headers.get("Content-Length", "0"))
            if length < 0 or length > MAX_REQUEST_BYTES:
                raise DemoError("请求过大", 413)
            payload = json.loads(self.rfile.read(length))
            if not isinstance(payload, dict):
                raise DemoError("工具参数必须为 JSON 对象", 400)
            name = parsed.path.removeprefix("/api/tools/")
            if parsed.path.startswith("/api/tools/") and name in FUNCTIONS:
                # 严格按对外工具契约接收参数；登录身份由适配器单独注入。
                schema = next(
                    item["function"]["parameters"] for item in TOOL_SCHEMAS if item["function"]["name"] == name
                )
                if set(payload) - set(schema["properties"]):
                    raise DemoError("工具参数包含未声明的字段", 400)
                if set(schema["required"]) - set(payload):
                    raise DemoError("工具参数缺少必填字段", 400)
                return self.respond(200, FUNCTIONS[name](viewer_id=viewer_id, **payload))
        return self.respond(404, {"error": "接口不存在"})

    def do_GET(self):
        self.handle_request()

    def do_POST(self):
        self.handle_request()

    def handle_request(self):
        # 权限错误和输入错误保留明确状态，方便页面显示和集成验收。
        try:
            self.dispatch()
        except DemoError as error:
            self.respond(error.status, {"error": str(error)})
        except (TypeError, ValueError, KeyError) as error:
            self.respond(400, {"error": str(error)})
        except Exception:
            LOGGER.exception("演示请求处理失败：%s %s", self.command, urlparse(self.path).path)
            self.respond(500, {"error": "演示服务处理失败，请检查容器日志"})


if __name__ == "__main__":
    # 容器内部监听 8080，Compose 只向本机发布 32770。
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")
    server = ThreadingHTTPServer(("0.0.0.0", 8080), Handler)
    print("Python demo listening on 8080", flush=True)
    server.serve_forever()
