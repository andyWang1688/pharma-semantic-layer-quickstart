import asyncio

from security.policy import rewrite_query

from cube import config


# Cube 原生请求钩子：默认 JWT 验签先完成，这里拿到的是验签后的 securityContext。
# 数据库权限解析直接发生在 Cube 进程，不通过 demo HTTP 服务回调。
@config("query_rewrite")
async def query_rewrite(query, context):
    # pg8000 使用同步 I/O；放在线程中执行，避免占用 Python 异步事件循环。
    return await asyncio.to_thread(rewrite_query, query, context.get("securityContext") or {})


# 只为验收隔离“必须命中预聚合”和“自动匹配”两种执行配置，不按工号建立聚合。
@config("context_to_orchestrator_id")
def context_to_orchestrator_id(context):
    security_context = context.get("securityContext") or {}
    return "ROLLUP_PROOF" if security_context.get("requireRollup") else "AUTOMATIC"


@config("orchestrator_options")
def orchestrator_options(context):
    security_context = context.get("securityContext") or {}
    # requireRollup 是受信签名上下文中的诊断开关，不能代替行权限。
    return {"rollupOnlyMode": bool(security_context.get("requireRollup"))}
