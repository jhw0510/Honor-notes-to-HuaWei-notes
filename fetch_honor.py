# -*- coding: utf-8 -*-
"""荣耀云备忘录全量抓取 -> notes_honor.json
流程：弹出浏览器 -> 你登录荣耀账号并进入备忘录 -> 脚本检测到登录后自动抓取全部笔记
（浏览器保持打开直到抓取完成）
"""
import asyncio, json, pathlib, re, html as ihtml

from playwright.async_api import async_playwright

BASE = pathlib.Path(__file__).parent
PROFILE = BASE / "profile_honor"
OUT = BASE / "notes_honor.json"

LIST_URL = "https://cloud.honor.com/portal/notepad/note/util/getNoteList"
DETAIL_URL = "https://cloud.honor.com/portal/notepad/noteDetail"
FOLDER_URL = "https://cloud.honor.com/portal/notepad/note/initDataBase/getFolderList"
COUNT_URL = "https://cloud.honor.com/portal/notepad/note/count"

BATCH = 20


def html_to_text(h: str) -> str:
    if not h:
        return ""
    h = re.sub(r'<(script|style)[^>]*>.*?</\1>', '', h, flags=re.S | re.I)
    h = re.sub(r'<li[^>]*>', '\n· ', h, flags=re.I)
    h = re.sub(r'</(p|div|li|ul|h\d)>', '\n', h, flags=re.I)
    h = re.sub(r'<br[^>]*>', '\n', h, flags=re.I)
    h = re.sub(r'<[^>]+>', '', h)
    h = ihtml.unescape(h)
    h = re.sub(r'[ \t　]+', ' ', h)
    h = re.sub(r'\n\s*\n+', '\n\n', h)
    return h.strip()


async def api(ctx, csrf, url, payload=None):
    headers = {
        "Content-Type": "application/json",
        "csrftoken": csrf,
        "Referer": "https://cloud.honor.com/portal/notepad?langCode=zh-cn",
        "Origin": "https://cloud.honor.com",
    }
    if payload is None:
        resp = await ctx.request.get(url, headers=headers)
    else:
        resp = await ctx.request.post(url, headers=headers, data=json.dumps(payload))
    body = await resp.text()
    if resp.status != 200:
        raise RuntimeError(f"{url} -> HTTP {resp.status}: {body[:200]}")
    j = json.loads(body)
    if j.get("code") != 0:
        raise RuntimeError(f"{url} -> code={j.get('code')} desc={j.get('desc')}")
    return j["data"]


async def wait_for_login(ctx, page, timeout=600):
    """等待用户登录：页面自己发 notepad 请求时带 csrftoken 头"""
    box = {"token": ""}

    def on_request(req):
        if "notepad" in req.url and req.headers.get("csrftoken"):
            box["token"] = req.headers["csrftoken"]

    ctx.on("request", on_request)
    print("等待登录...（登录并看到笔记列表后会自动继续，无需其他操作）")
    waited = 0
    while not box["token"] and waited < timeout:
        await page.wait_for_timeout(1000)
        waited += 1
        if waited % 60 == 0:
            print(f"  仍在等待登录...({waited}s)")
    ctx.remove_listener("request", on_request)
    return box["token"]


COOKIES = BASE / "cookies_honor.json"


async def main():
    pw = await async_playwright().start()
    ctx = await pw.chromium.launch_persistent_context(
        user_data_dir=str(PROFILE), channel="msedge", headless=False,
        viewport={"width": 1100, "height": 720},
        args=["--disable-blink-features=AutomationControlled"])
    page = ctx.pages[0] if ctx.pages else await ctx.new_page()

    # 恢复上次保存的登录 cookie（如果有）
    if COOKIES.exists():
        try:
            saved = json.loads(COOKIES.read_text(encoding="utf-8"))
            await ctx.add_cookies(saved)
            print(f"已恢复 {len(saved)} 个历史 cookie")
        except Exception as e:
            print("恢复 cookie 失败:", e)

    try:
        await page.goto("https://cloud.honor.com/portal/notepad?langCode=zh-cn",
                        wait_until="domcontentloaded", timeout=60000)

        csrf = await wait_for_login(ctx, page)
        if not csrf:
            print("等待超时，未检测到登录。")
            return
        print(f"检测到登录，csrftoken={csrf[:12]}... 开始抓取")

        # 保存登录 cookie，下次免登录
        try:
            all_cookies = await ctx.cookies()
            COOKIES.write_text(json.dumps(all_cookies, ensure_ascii=False),
                               encoding="utf-8")
        except Exception as e:
            print("保存 cookie 失败:", e)

        count = await api(ctx, csrf, COUNT_URL)
        print("云端笔记统计:", json.dumps(count, ensure_ascii=False))

        folders_raw = await api(ctx, csrf, FOLDER_URL, {})
        folders = {f["uuid"]: f.get("display_name", "") for f in folders_raw}
        print(f"文件夹 {len(folders)} 个")

        note_list = await api(ctx, csrf, LIST_URL,
                              {"queryType": 1, "category": "total", "searchContent": ""})
        print(f"笔记列表 {len(note_list)} 条")

        uuid_to_meta = {n["uuid"]: n for n in note_list}
        uuids = list(uuid_to_meta.keys())
        details = {}
        for i in range(0, len(uuids), BATCH):
            chunk = uuids[i:i + BATCH]
            try:
                data = await api(ctx, csrf, DETAIL_URL, {"noteIds": chunk})
            except Exception as e:
                print(f"\n批次 {i}-{i+len(chunk)} 失败，降级逐条:", e)
                data = []
                for u in chunk:
                    try:
                        data.extend(await api(ctx, csrf, DETAIL_URL, {"noteIds": [u]}))
                    except Exception as e2:
                        print(f"  单条 {u} 失败: {e2}")
            for d in data:
                details[d["uuid"]] = d
            print(f"\r详情进度 {min(i + BATCH, len(uuids))}/{len(uuids)}", end="", flush=True)
        print()

        notes, skipped_locked = [], []
        for u in uuids:
            meta = uuid_to_meta[u]
            d = details.get(u, {})
            if d.get("lock_status") or meta.get("lock_status"):
                skipped_locked.append(meta.get("title") or u)
                continue
            html_content = d.get("html_content") or ""
            text = html_to_text(html_content)
            if not text:
                text = (d.get("summary") or meta.get("summary") or "").strip()
            notes.append({
                "uuid": u,
                "title": d.get("title") or meta.get("title") or "",
                "folder": folders.get(meta.get("folder_uuid") or d.get("folder_uuid"), ""),
                "create_time": d.get("create_time") or meta.get("create_time"),
                "modify_time": d.get("modify_time") or meta.get("modify_time"),
                "has_record": d.get("has_record", meta.get("has_record", 0)),
                "has_attach": d.get("has_attach", meta.get("has_attach", 0)),
                "html_content": html_content,
                "text": text,
            })

        with open(OUT, "w", encoding="utf-8") as f:
            json.dump(notes, f, ensure_ascii=False, indent=1)
        no_text = [n for n in notes if not n["text"]]
        print(f"\n已导出 {len(notes)} 条 -> {OUT}")
        print(f"其中无文字内容（纯录音/图片）: {len(no_text)} 条")
        if skipped_locked:
            print(f"加密跳过: {len(skipped_locked)} 条: {skipped_locked}")
    finally:
        await ctx.close()
        await pw.stop()

asyncio.run(main())
