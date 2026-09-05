# -*- coding: utf-8 -*-
"""荣耀云备忘录 API 抓包：打开浏览器，用户手动登录后自动记录 notepad 相关请求。
使用方法：运行后会弹出 Edge 浏览器
1. 登录荣耀账号（如已登录会直接进）
2. 进入备忘录页面，滚动列表到底（触发分页加载）
3. 随便点开 2~3 条笔记看详情
4. 直接关闭浏览器窗口，抓包数据自动保存到 capture_honor.jsonl
"""
import asyncio, json, pathlib

from playwright.async_api import async_playwright

BASE = pathlib.Path(__file__).parent
CAPTURE = BASE / "capture_honor.jsonl"
PROFILE = BASE / "profile_honor"

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
            interesting = ("notepad" in url.lower()) or ("json" in ct and "honor" in url.lower())
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
                "resp_body": body[:200000] if body else None,
            })
            print(f"[CAP] {req.method} {url[:110]} -> {resp.status}")
        except Exception:
            pass

    page.on("response", lambda r: asyncio.ensure_future(on_response(r)))

    await page.goto("https://cloud.honor.com/portal/notepad?langCode=zh-cn")
    print("=" * 60)
    print("请在浏览器中：登录 -> 打开备忘录 -> 滚动列表到底 -> 点开几条笔记")
    print("完成后直接关闭浏览器窗口")
    print("=" * 60)

    # 等用户关闭所有页面/浏览器
    while ctx.pages:
        await asyncio.sleep(1)
        for p in ctx.pages:
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
