# 家庭共享与 iCloud+ 接口研究及接入范围

核对日期：2026-11-10。

## 已合入的功能

账号管理中每个账号的「家庭与方案」按钮可以查询家庭成员、本人角色、iCloud+ 来源（个人、家庭共享、Apple One 等）和空间用量。查询使用该账号现有的 iCloud Web 会话及已保存区域，复用服务器的 Apple 专用网络路线。

`GET /api/accounts/<account_id>/benefits` 需要管理员登录，响应禁止缓存。各项查询独立返回 `ok`；上游超时、会话过期和响应缺失都不会当作「未加入家庭」或「未订阅」。所有查询只尝试一次，不修改账号、密码、库存或 Apple 家庭设置。

Apple 返回的 `webservices.account.url` 必须是当前区域的 HTTPS setup 主机。验证得到的 dsid 仅用于该账号查询，不使用库中的默认 dsid。查询只保留页面需要的成员姓名、Apple ID、角色和容量字段。

## GitHub 来源

| 项目 | 实际找到的内容 | 接入判断 |
| --- | --- | --- |
| [timlaing/pyicloud 的 account.py](https://github.com/timlaing/pyicloud/blob/main/pyicloud/services/account.py)（本项目依赖 2026.10.1，MIT） | 家庭、存储、订阅查询，定义 pricing URL；没有加入家庭或购买方案方法 | 依据请求契约编写本项目适配层。家庭、存储、订阅查询已在部署服务器上只读验证；pricing 返回 400，未把它当作套餐报价 API 上线。 |
| [saloonphp-apple-client / FamilyResources](https://github.com/jackchang1025/saloonphp-apple-client/blob/cfc86fdbaf1729b4ced01c68d874ea78662dc536/src/Resource/SetupIcloud/FamilyResources.php) | 创建家庭、添加/移除成员、退出家庭 | 确实存在成员操作代码，不能说「没有接口」。但其 [认证代码](https://github.com/jackchang1025/saloonphp-apple-client/blob/cfc86fdbaf1729b4ced01c68d874ea78662dc536/src/Resource/SetupIcloud/SetupIcloudResource.php) 使用 dsid + mmeAuthToken 的 Basic Auth；添加成员先验证付款方式 CVV，再传成员账号及密码。不能直接复用本项目 Web Cookie，未验证现代双重认证及中国区行为，未移植这些写操作。 |
| [saloonphp-apple-client / Buy](https://github.com/jackchang1025/saloonphp-apple-client/tree/cfc86fdbaf1729b4ced01c68d874ea78662dc536/src/Integrations/Buy) | 读取/添加付款信息等 | 目录名 Buy 不等于 iCloud+ 下单 API；没有发现选择 iCloud+ 套餐并完成付款的实现。 |
| [yb1320057104/ic-mail](https://github.com/yb1320057104/ic-mail/tree/1a49ef9f42be73f583bf9ed2e960c76529c955bb) | Apple 登录、隐藏邮件地址、会员资格判断 | 未发现家庭加入或 iCloud+ 购买实现，未复制源码。 |
| [fix-macosx/yosemite-phone-home](https://github.com/fix-macosx/yosemite-phone-home) | 2014 年协议日志包含 acceptInvitation 等端点名称 | 缺少可用于当前认证的完整契约；不依据名称猜测写请求。 |

另行核对了 Apple 当前公开 Web 客户端（2640Build24）：家庭、订阅查询路径一致；订阅流程还涉及 upsell 页面、Apple 购买界面与在设备继续操作。没有将页面渲染或购买后提示接口误当成扣款接口。

## 上游只读请求

- `GET {webservices.account.url}/setup/web/family/getFamilyDetails`
- `POST {webservices.account.url}/setup/ws/1/storageUsageInfo`（仅查询容量）
- `GET https://gatewayws.{account.host}/acsegateway/v3/accounts/{validated_dsid}/subscriptions/features/cloud.storage/plan-summary`

家庭成员身份与「正在使用家庭共享存储」是不同概念。页面分别使用家庭接口和 `includedWithSharedPlan`，不会因为在一个家庭中就断言已共享 iCloud+。`isHideMyEmailSubscriptionActive` 单独展示，不根据容量或 HME 服务地址推断是否已付款。

## 加入与付费的实际边界

**当前版本不支持在工作台直接接受家庭邀请、创建家庭或提交 iCloud+ 订单。** 已接入的流程是：从工作台打开 Apple 官方入口，用户在那里确认，返回工作台刷新真实状态。它不是自动加入或自动扣款。

- 家庭邀请：支持在当前页面粘贴 Apple 的 HTTPS `setup.icloud.com` / `setup.icloud.com.cn` 的 `/family/messages?aaaction=showFamilyInvite&inviteCode=...` 邀请链接并打开。不上传、保存、抓取或自动接受邀请。其他邀请格式从原始邮件/短信打开。
- iCloud+：按已保存的账号区域打开 `https://www.icloud.com/plan/` 或 `https://www.icloud.com.cn/plan/`；套餐价格和付款在 Apple 确认，工作台不保存银行卡或 CVV。
- 浏览器和设备的 Apple 登录状态独立于工作台，用户需要核对账号。返回后「刷新状态」不会把点击链接视为开通成功。

Apple 官方资料：[加入家庭](https://support.apple.com/zh-cn/108380)、[购买或升级 iCloud+](https://support.apple.com/zh-cn/108349)、[iCloud+ 开通入口](https://www.apple.com/icloud/)。

若后续实现原生家庭写接口，需要单独完成其认证、成员验证、区域行为、确认与重复提交控制，并在获授权的测试家庭中验证；不能仅把 PHP URL 搬过来就宣称已支持。
