#!/bin/sh
# 固定配置目录；项目名、端口和令牌密钥由 Compose 的 .env/环境变量解析。
set -eu
example_dir=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
compose() {
  docker compose --project-directory "$example_dir" -f "$example_dir/compose.yml" "$@"
}
build_models() {
  # 全量 dbt DAG 逐表发布；重建期间停掉消费者，成功后再开放查询。
  # 构建失败时保留停止状态，防止用户查询混合版本的 Mart。
  compose stop demo cube
  compose run --rm --no-deps dbt build --profiles-dir .
  compose up -d --no-deps --wait cube demo
}
check_code() {
  # 只检查挂载源码；Ruff 缓存放在临时容器中。
  compose run --rm --no-deps demo ruff check --no-cache /example
  compose run --rm --no-deps demo ruff format --check --no-cache /example
  compose run --rm --no-deps demo python -m unittest discover -s /example/tests -p test_policy.py
}
case "${1:-up}" in
  up)
    # 保留正在运行的 tmpfs 数据库，只升级本例服务和转换任务。
    compose up -d --no-recreate --wait db
    # Docker 层缓存复用未变依赖；依赖文件变更时镜像也会及时更新。
    compose build dbt cube demo
    build_models
    address=$(compose port demo 8080)
    case "$address" in
      127.0.0.1:[1-9]*) ;;
      *) echo "Local demo port was not published: $address" >&2; exit 1 ;;
    esac
    echo "http://$address"
    ;;
  build)
    # 源数据变更后主动重建组织/事实模型；成功后恢复 Cube 与页面。
    build_models
    ;;
  check)
    compose config --quiet
    compose build demo
    check_code
    ;;
  test)
    compose config --quiet
    compose build demo
    check_code
    build_models
    # 数据质量是第一道门：重复、外键、类型和组织循环有问题就停止业务验收。
    compose exec -T demo python /example/tests/test_data_quality.py
    # 先跑完整集成，再停常驻 demo 服务证明 Cube 自己执行权限。
    compose exec -T demo python /example/tests/test_integration.py
    # 单独验证 dbt 刷新边界、未来版本、实时撤权和停用；所有夹具最后恢复。
    compose run --rm --no-deps --entrypoint python dbt /example/tests/test_dbt_refresh.py
    # 刷新测试恢复后再次核对全量基准数据与分层。
    compose exec -T demo python /example/tests/test_data_quality.py
    compose stop demo
    # 验收失败或中断也恢复页面，便于继续 review。
    trap 'compose up -d --no-deps --wait demo >/dev/null' EXIT HUP INT TERM
    compose run --rm --no-deps demo python /example/tests/test_cube_only.py
    compose up -d --no-deps --wait demo
    trap - EXIT HUP INT TERM
    ;;
  token)
    # 本地示例身份令牌，有效两分钟；不是生产登录接口。
    compose run --rm --no-deps demo python -c 'import sys; from cube_client import sign_context; print(sign_context({"viewerEmployeeCode": sys.argv[1]}))' "${2:-M001}"
    ;;
  down)
    # 数据库使用 tmpfs：关闭本例会丢弃合成数据，下次启动重新初始化。
    compose down
    ;;
  *)
    echo "Usage: sh run.sh [up|build|check|test|token [employee]|down]" >&2
    exit 1
    ;;
esac
