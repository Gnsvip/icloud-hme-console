# 验证范围

前端验证：在 `frontend/` 中运行 `npm ci`、`npm run build`、`npm test`。

后端验证：安装 `requirements.txt` 和 `pytest` 后运行 `python -m pytest tests/test_redesign.py tests/test_public_config.py -q`。`tests/conftest.py` 仅为测试进程设置测试密码；该值不是 Web 服务的默认密码。

历史回归检查保留于 `tests/test_regressions.py`。原始服务源码与界面改版后的源码，在相同依赖环境下均为 49 项通过、7 项失败。已知失败为：

- `public_pickup_accepts_email_and_returns_latest_two_messages`
- `public_pickup_plus_alias_queries_base_address`
- `public_pickup_has_no_rate_limit`
- `qq_imap_pickup_uses_full_tag_and_falls_back_after_icloud`
- `pickup_page_only_asks_for_email`
- `legacy_pickup_credentials_are_removed`
- `multi_alias_search_forward_bindings_and_scheduler_countdown_are_wired`

前四项仍调用已不存在的 `api_public_code`；后三项检查旧页面或旧脚本文本。此仓库保留这些检查以记录差异，不会为了旧测试恢复匿名查件接口、删除现有鉴权或忽略失败。

新测试采用临时缓存和合成邮件，不需要真实 iCloud Cookie。真实账号创建/删除、Microsoft 外部授权与转发邮箱连接需要单独进行集成验证。

`tests/benchmark_redesign.py` 可对比一个旧版源码目录的缓存写入行为。它只生成合成数据；运行方式为 `python tests/benchmark_redesign.py /path/to/baseline`。
