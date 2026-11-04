# 验证范围

后端：安装 `requirements.txt` 和 `pytest`，运行 `python -m pytest tests -q`。所有测试共用临时运行目录，不读取或修改部署数据，也不连接真实邮箱。测试账号和密码仅用于测试进程。

前端：在 `frontend/` 运行 `npm ci`、`npm test`、`npm run build`。覆盖登录状态、失败保留数据、隐藏页面停止轮询、跨账号邮件隔离、分页选择、批量创建与懒加载页面切换。

历史回归测试已更新到现有接口：共享取码服务和带令牌的 `/c/`、`/api/public/latest-code/`。退役的匿名邮箱查询入口保持不可用。测试没有跳过或忽略旧失败。

`tests/test_optimizations.py` 覆盖库存原子写入失败、损坏文件保护、并发读写、查询缓存失效、日志队列容量、真实本地 socket 超时中断、任务排队上限、异常连接清理，以及缓存期限、条数和字节上限。

GitHub Actions 在每次推送和 PR 时运行后端与前端检查。后端覆盖 Linux 的 Python 3.10 / 3.13 和 Windows 的 Python 3.13；前端使用 Node.js 24。工作流仅有仓库读取权限，不部署服务器。

真实账号创建/删除、Microsoft 外部授权与真实邮箱连接仍需单独进行集成验证。`tests/benchmark_redesign.py` 使用合成数据评估缓存批量写入，测量不代表真实邮件网络速度。
