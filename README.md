# Honor Notes → Huawei Notes 迁移工具（Python 版）

把**荣耀手机备忘录**（MagicOS 7 及以上，荣耀云）里的笔记批量迁移到**华为手机备忘录**（鸿蒙，华为云）的免费开源工具。作者本人从荣耀换机到华为后，不想为这类一次性小功能付费，于是用 Python + Playwright 复现了迁移全流程。

## 原理

两家的云端备忘录都有网页版，本工具通过浏览器自动化拿到登录态后，直接调用云端接口：

| 方向 | 服务 | 关键接口 |
| --- | --- | --- |
| 读取 | 荣耀云 cloud.honor.com | `/portal/notepad/note/initDataBase/count`、`/getNoteList`、`/getNoteInfoList` |
| 写入 | 华为云 cloud.huawei.com | `/notepad/simplenote/query`、`/notepad/note/create` |

- 登录过程完全在你本机浏览器里手动完成，账号密码不经过任何第三方
- 华为端的写入请求**在备忘录网页自身的上下文中发出**（`page.evaluate` + `fetch`），与网页版行为一致，避免会话中途失效
- 保留原笔记的**创建时间 / 修改时间**，按时间正序写入

## 能迁移什么 / 不能迁移什么

| 内容 | 支持情况 |
| --- | --- |
| 笔记标题、纯文字正文（含换行） | ✅ 完整迁移 |
| 荣耀端**加密笔记** | ❌ 跳过（云端接口不返回密文内容） |
| 录音、图片等附件 | ❌ 仅迁移文字部分；纯录音/图片笔记会生成占位文字提示 |
| 待办勾选、提醒、标签、收藏状态 | ❌ 不迁移 |

## 环境要求

- Windows + 系统自带 **Edge 浏览器**（脚本通过 `channel="msedge"` 复用本机 Edge，无需下载 Chromium）
- Python 3.10+

```bash
pip install -r requirements.txt
playwright install   # 如本机 Edge 无法拉起再执行
```

## 使用步骤

### 1. 导出荣耀笔记

```bash
python fetch_honor.py
```

- 弹出 Edge 打开荣耀云登录页，**手动登录荣耀账号**
- 登录后脚本自动获取接口鉴权，全量抓取笔记（约 1 秒/条）
- 产物：`notes_honor.json`（全部笔记）、`cookies_honor.json`（会话缓存，短期内重跑免登录）

### 2. 写入华为备忘录

```bash
python push_huawei.py
```

- 弹出 Edge 打开华为云，**手动登录华为账号并打开"备忘录"应用**
- 脚本自动批量创建笔记；进度实时保存在 `push_progress.json`
- **支持断点续传**：中断后重新运行会自动跳过已成功的笔记
- 跑完后自动核对华为端笔记总数，失败列表写入 `push_failed.json`（重新运行可重试）

### 3.（可选）抓包 / 诊断工具

接口如有变动，可重新抓包分析：

```bash
python sniff_honor.py     # 登录荣耀云并操作备忘录，请求记录到 capture_honor.jsonl
python sniff_huawei.py    # 同理，记录到 capture_huawei.jsonl
python analyze_capture.py # 汇总荣耀抓包中的接口清单
python analyze_huawei.py  # 查看华为抓包中 create/query 的请求格式
```

## 常见问题

- **荣耀端 404/405**：`getFolderList` 等接口要求 POST 空 JSON，GET 会 405；脚本已处理
- **华为端跑到一半 401**：会话令牌会轮换。新版脚本在备忘录页面上下文内发请求并每次现取 `CSRFToken` cookie，已解决；如仍遇到，脚本会在连续失败时自动刷新页面重建会话（可能需要你重新点一下备忘录）
- **华为网页版入口 404**：备忘录 API 在 `cloud.huawei.com/notepad/*`，但网页应用需从 `cloud.huawei.com` 首页点击"备忘录"进入，直接访问 `/notepad` 会 404

## 隐私与安全

- 所有数据只经过你自己的浏览器和两家官方云端，无任何第三方服务器
- `.gitignore` 已排除全部敏感产物（cookie、抓包记录、笔记数据、浏览器 profile），**请勿手动提交这些文件**
- 本项目仅供个人数据迁移学习交流使用，与荣耀、华为官方无关；接口为私有接口，可能随时变动
