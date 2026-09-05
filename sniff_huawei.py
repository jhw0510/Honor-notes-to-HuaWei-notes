# -*- coding: utf-8 -*-
"""华为云备忘录 API 抓包：打开浏览器，用户手动登录后自动记录 notepad 相关请求。
使用方法：运行后弹出 Edge 浏览器
1. 登录华为账号
2. 打开【备忘录】应用（云空间网页版左侧/列表里找）
3. 等笔记列表加载出来，点开 1 条已有笔记
4. 【重要】手动新建 1 条测试笔记，内容写：测试迁移123，保存
5. 直接关闭浏览器窗口，抓包数据自动保存到 capture_huawei.jsonl
"""
import asyncio, json, pathlib

from playwright.async_api import async_playwright

BASE = pathlib.Path(__file__).parent
CAPTURE = BASE / "capture_huawei.jsonl"
PROFILE = BASE / "profile_huawei"

async def main():
    pw = await async_playwright().start()
    ctx = await pw.chromium.launch_persistent_context(
        user_data_dir=str(PROFILE),
        channel="msedge",
        headless=False,
        viewport={"width": 1280, "height": 860},
        args=["--disable-blink-features=AutomationControlled"],
    )
    page = ctx.pages[0] if ctx.pages else await ctx.new_page()

    records = []

    async def on_response(resp):
        try:
            url = resp.url
            ct = (resp.headers.get("content-type") or "").lower()
            ul = url.lower()
            interesting = ("notepad" in ul) or ("note" in ul and "json" in ct)
            if not interesting:
                return
            body = None
            try:
                body = await resp.body()
                body = body.decode("utf-8", "replace")
            except Exception:
                pass
            req = resp.request
            records.append({
                "url": url,
                "method": req.method,
                "req_headers": await req.all_headers(),
                "post_data": req.post_data,
                "status": resp.status,
                "resp_body": body[:500000] if body else None,
            })
            print(f"[CAP] {req.method} {url[:120]} -> {resp.status}")
        except Exception:
            pass

    page.on("response", lambda r: asyncio.ensure_future(on_response(r)))

    await page.goto("https://cloud.huawei.com/")
    print("=" * 60)
    print("请在浏览器中：")
    print("1. 登录华为账号")
    print("2. 打开【备忘录】，等列表加载，点开 1 条已有笔记")
    print("3. 新建 1 条测试笔记（内容：测试迁移123），保存")
    print("4. 完成后直接关闭浏览器窗口")
    print("=" * 60)

    while ctx.pages:
        await asyncio.sleep(1)
        for p in list(ctx.pages):
            if p.is_closed():
                try:
                    ctx.pages.remove(p)
                except ValueError:
                    pass

    with open(CAPTURE, "w", encoding="utf-8") as f:
        for r in records:
            f.write(json.dumps(r, ensure_ascii=False) + "\n")
    await ctx.close()
    await pw.stop()
    print(f"已保存 {len(records)} 条记录到 {CAPTURE}")

asyncio.run(main())
