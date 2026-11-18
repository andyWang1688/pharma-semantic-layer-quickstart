"""Cube REST 客户端和合成身份签发器；不参与业务授权范围的计算。"""

import base64
import hashlib
import hmac
import json
import os
import time
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from security.database import DemoError

QUERY_TIMEOUT_SECONDS = 60


def sign_context(security_context: dict) -> str:
    """本机示例 HS256 令牌，有效两分钟；正式接入由认证系统签发。"""

    def encode(value):
        return base64.urlsafe_b64encode(json.dumps(value, separators=(",", ":")).encode()).rstrip(b"=")

    header = encode({"alg": "HS256", "typ": "JWT"})
    payload = encode({**security_context, "iat": int(time.time()), "exp": int(time.time()) + 120})
    signing_input = header + b"." + payload
    signature = hmac.new(
        os.environ.get("CUBE_API_SECRET", "shared-sales-example-secret").encode(),
        signing_input,
        hashlib.sha256,
    ).digest()
    return (signing_input + b"." + base64.urlsafe_b64encode(signature).rstrip(b"=")).decode()


def cube_request(endpoint: str, security_context: dict, cube_query: dict) -> tuple[int, dict]:
    """发送标准 Cube 请求，在总时限内处理 Continue wait；返回状态和响应对象。

    令牌和完整请求体不会写日志。网络错误、超时及无效响应明确失败。
    endpoint 来自应用内部常量，查询参数统一编码成 JSON。
    """
    token = sign_context(security_context)
    base_url = os.environ.get("CUBE_API_URL", "http://cube:4000/cubejs-api/v1")
    deadline = time.monotonic() + QUERY_TIMEOUT_SECONDS
    while (remaining := deadline - time.monotonic()) > 0:
        request = Request(
            f"{base_url}/{endpoint}",
            data=json.dumps({"query": cube_query}).encode(),
            headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json"},
            method="POST",
        )
        try:
            try:
                with urlopen(request, timeout=min(25, remaining)) as response:
                    status, body = response.status, json.load(response)
            except HTTPError as error:
                with error:
                    status, body = error.code, json.load(error)
        except (URLError, TimeoutError):
            raise DemoError("Cube 连接失败或查询超时", 502) from None
        except (ValueError, UnicodeError):
            raise DemoError("Cube 返回了无效 JSON 响应", 502) from None
        if not isinstance(body, dict):
            raise DemoError("Cube 返回了无效的响应结构", 502)
        if body.get("error") != "Continue wait":
            return status, body
        time.sleep(min(0.2, max(0, deadline - time.monotonic())))
    raise DemoError(f"Cube 查询超过 {QUERY_TIMEOUT_SECONDS} 秒，请稍后重试", 504)
