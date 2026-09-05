# -*- coding: utf-8 -*-
"""把 notes_honor.json 里的笔记批量写入华为云备忘录
流程：弹出浏览器 -> 登录华为账号并打开备忘录 -> 脚本自动批量创建
支持断点续传：中断后重新运行会跳过已成功的笔记
"""
import asyncio, json, pathlib, random, sys, time, html as ihtml

from playwright.async_api import async_playwright

BASE = pathlib.Path(__file__).parent
PROFILE = BASE / "profile_huawei"
NOTES_IN = BASE / (sys.argv[1] if len(sys.argv) > 1 else "notes_honor.json")
PROGRESS = BASE / "push_progress.json"   # honor_uuid -> huawei guid
FAILED = BASE / "push_failed.json"
COOKIES = BASE / "cookies_huawei.json"
HEADERS_FILE = BASE / "headers_huawei.json"

API = "https://cloud.huawei.com"
SIMPLENOTE_QUERY = API + "/notepad/simplenote/query"
NOTE_CREATE = API + "/notepad/note/create"

DELAY = 0.7          # 每条间隔（秒）
RETRY = 3


def make_trace_id():
    return f"03131_02_{int(time.time())}_{random.randint(10000000, 99999999)}"


def make_guid():
    return f"newNote{random.randint(0, 0xFFFF):04x}-{int(time.time() * 1000)}-{random.randint(10000, 99999)}"


def build_create_body(note, start_cursor):
    text = (note.get("text") or "").strip()
    title_src = note.get("title") or ""
    if not text:
        text = (title_src + "\n（此条在荣耀端为录音/图片笔记，无文字内容，请到旧手机查看原内容）").strip()
    first_line = text.split("\n", 1)[0][:64]

    created = note.get("create_time") or int(time.time() * 1000)
    modified = note.get("modify_time") or created
    guid = make_guid()

    inner_content = {
        "filedir": "", "delete_flag": 0, "fold_id": 0, "is_lunar": 0,
        "need_reminded": 0, "prefix_uuid": "", "unstruct_uuid": "",
        "created": created, "data6": "0",
        "data5": json.dumps({"data1": first_line, "data2": "auto", "data4": "1"},
                            ensure_ascii=False),
        "content": "Text|" + text,
        "html_content": '<note><element type="Text">' + ihtml.escape(text, quote=False) + "</element></note>",
        "title": first_line + "\n" + text,
        "favorite": 0, "has_todo": 0, "tag_id": "", "first_attach_name": "",
        "has_attachment": 0, "modified": modified,
        "unstructure": "[]", "version": "12", "data3": "",
    }
    inner = {
        "guid": guid,
        "simpleNote": "",
        "fileList": [],
        "content": inner_content,
        "currentNotePadVersion": f"7b98-{int(time.time() * 1000)}-{random.randint(10000, 99999)}",
    }
    return {
        "reqInfo": {"kind": "note", "data": json.dumps(inner, ensure_ascii=False),
                    "simpleNote": ""},
        "ctagNoteInfo": "",
        "startCursor": str(start_cursor),
        "guid": guid,
        "traceId": make_trace_id(),
    }


JS_FETCH = r"""async ({url, headers, payload}) => {
  const m = document.cookie.match(/(?:^|;\s*)CSRFToken=([^;]+)/i);
  const h = Object.assign({}, headers);
  if (m) h['csrftoken'] = decodeURIComponent(m[1]);
  const resp = await fetch(url, {
    method: 'POST',
    headers: h,
    body: JSON.stringify(payload),
    credentials: 'include'
  });
  const text = await resp.text();
  return {status: resp.status, text};
}"""


async def api(page, headers, url, payload):
    """在备忘录页面上下文里发请求，和网页版自身行为完全一致
    （csrftoken 每次从 document.cookie 现取，解决令牌轮换导致的 401）"""
    r = await asyncio.wait_for(
        page.evaluate(JS_FETCH, {"url": url, "headers": headers, "payload": payload}),
        timeout=30)
    if r["status"] != 200:
        raise RuntimeError(f"HTTP {r['status']}: {r['text'][:200]}")
    j = json.loads(r["text"])
    result = j.get("Result") or {}
    if result.get("code") not in ("0", None):
        raise RuntimeError(f"code={result.get('code')} desc={result.get('desc')}")
    return j


async def wait_for_login(ctx, page, timeout=600):
    """等待用户登录华为并打开备忘录，抓取鉴权头"""
    box = {"headers": None}

    def on_request(req):
        if "/notepad/" in req.url and req.headers.get("csrftoken") and not box["headers"]:
            h = req.headers
            box["headers"] = {
                "csrftoken": h["csrftoken"],
                "content-type": "application/json;charset=UTF-8",
                "referer": "https://cloud.huawei.com/notepad",
                "x-hw-account-brand-id": h.get("x-hw-account-brand-id", "0"),
                "x-hw-app-brand-id": h.get("x-hw-app-brand-id", "1"),
                "x-hw-client-mode": h.get("x-hw-client-mode", "frontend"),
                "x-hw-device-brand": h.get("x-hw-device-brand", "HUAWEI"),
                "x-hw-device-category": h.get("x-hw-device-category", "Web"),
                "x-hw-device-id": h.get("x-hw-device-id", ""),
                "x-hw-device-manufacturer": h.get("x-hw-device-manufacturer", "HUAWEI"),
                "x-hw-device-type": h.get("x-hw-device-type", "7"),
                "x-hw-os-brand": h.get("x-hw-os-brand", "Web"),
            }

    ctx.on("request", on_request)
    print("等待登录华为云并打开【备忘录】...（打开备忘录后自动继续）")
    waited = 0
    while not box["headers"] and waited < timeout:
        await page.wait_for_timeout(1000)
        waited += 1
        if waited % 60 == 0:
            print(f"  仍在等待...({waited}s)")
    ctx.remove_listener("request", on_request)
    return box["headers"]


async def main():
    notes = json.loads(NOTES_IN.read_text(encoding="utf-8"))
    progress = json.loads(PROGRESS.read_text(encoding="utf-8")) if PROGRESS.exists() else {}
    failed = {}

    pw = await async_playwright().start()
    ctx = await pw.chromium.launch_persistent_context(
        user_data_dir=str(PROFILE), channel="msedge", headless=False,
        viewport={"width": 1100, "height": 720},
        args=["--disable-blink-features=AutomationControlled"])
    page = ctx.pages[0] if ctx.pages else await ctx.new_page()

    if COOKIES.exists():
        try:
            await ctx.add_cookies(json.loads(COOKIES.read_text(encoding="utf-8")))
            print("已恢复历史 cookie")
        except Exception:
            pass

    try:
        await page.goto("https://cloud.huawei.com/",
                        wait_until="domcontentloaded", timeout=60000)

        headers = None
        if HEADERS_FILE.exists() and COOKIES.exists():
            headers = json.loads(HEADERS_FILE.read_text(encoding="utf-8"))
            try:
                await api(page, headers, SIMPLENOTE_QUERY,
                          {"index": 0, "status": 0, "guids": "", "traceId": make_trace_id()})
                print("复用历史鉴权成功，无需重新登录")
            except Exception as e:
                print(f"历史鉴权失效({e})，转为手动登录")
                headers = None
        if not headers:
            headers = await wait_for_login(ctx, page)
        if not headers:
            print("等待超时，未检测到备忘录请求。")
            return
        print("已获取华为鉴权信息")
        HEADERS_FILE.write_text(json.dumps(headers, ensure_ascii=False), encoding="utf-8")

        try:
            COOKIES.write_text(json.dumps(await ctx.cookies(), ensure_ascii=False),
                               encoding="utf-8")
        except Exception:
            pass

        # 基线
        base = await api(page, headers, SIMPLENOTE_QUERY,
                         {"index": 0, "status": 0, "guids": "", "traceId": make_trace_id()})
        start_cursor = base.get("startCursor", "0")
        base_count = len((base.get("rspInfo") or {}).get("noteList") or [])
        print(f"华为端现有笔记 {base_count} 条，startCursor={start_cursor}")

        todo = [n for n in notes if n["uuid"] not in progress]
        print(f"待迁移 {len(todo)} 条（已完成 {len(progress)} 条）")

        consec_fail = 0
        for idx, note in enumerate(todo, 1):
            ok = False
            for attempt in range(RETRY):
                try:
                    body = build_create_body(note, start_cursor)
                    r = await api(page, headers, NOTE_CREATE, body)
                    start_cursor = r.get("startCursor", start_cursor)
                    hw_guid = ((r.get("rspInfo") or {}).get("guid")) or ""
                    progress[note["uuid"]] = hw_guid
                    ok = True
                    break
                except Exception as e:
                    print(f"\n  第{idx}条 第{attempt+1}次失败: {e}", flush=True)
                    await asyncio.sleep(2 * (attempt + 1))
            if not ok:
                failed[note["uuid"]] = note.get("title") or note["uuid"]
                consec_fail += 1
            else:
                consec_fail = 0

            PROGRESS.write_text(json.dumps(progress, ensure_ascii=False),
                                encoding="utf-8")
            print(f"\r进度 {idx}/{len(todo)}  失败 {len(failed)}", end="", flush=True)

            if consec_fail >= 5:
                print("\n连续失败，刷新页面重新获取会话（如弹出登录请手动登录并打开备忘录）...", flush=True)
                try:
                    await page.reload(wait_until="domcontentloaded", timeout=60000)
                except Exception:
                    pass
                new_headers = await wait_for_login(ctx, page, timeout=300)
                if new_headers:
                    headers.clear()
                    headers.update(new_headers)
                    HEADERS_FILE.write_text(json.dumps(headers, ensure_ascii=False),
                                            encoding="utf-8")
                    # 重新取游标
                    base = await api(page, headers, SIMPLENOTE_QUERY,
                                     {"index": 0, "status": 0, "guids": "",
                                      "traceId": make_trace_id()})
                    start_cursor = base.get("startCursor", start_cursor)
                    print("会话已恢复，继续写入", flush=True)
                consec_fail = 0

            await asyncio.sleep(DELAY + random.uniform(0, 0.6))

        PROGRESS.write_text(json.dumps(progress, ensure_ascii=False), encoding="utf-8")
        FAILED.write_text(json.dumps(failed, ensure_ascii=False, indent=1), encoding="utf-8")

        # 核对
        end = await api(page, headers, SIMPLENOTE_QUERY,
                        {"index": 0, "status": 0, "guids": "", "traceId": make_trace_id()})
        end_count = len((end.get("rspInfo") or {}).get("noteList") or [])
        print(f"\n\n完成：成功 {len(progress)} 条，失败 {len(failed)} 条")
        print(f"华为端笔记数: {base_count} -> {end_count}（新增 {end_count - base_count}）")
        if failed:
            print("失败列表见 push_failed.json")
    finally:
        await ctx.close()
        await pw.stop()

asyncio.run(main())
