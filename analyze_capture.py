# -*- coding: utf-8 -*-
"""分析抓包文件：每个接口的请求参数和响应结构"""
import json, collections, pathlib

CAP = pathlib.Path(__file__).parent / "capture_honor.jsonl"
recs = [json.loads(l) for l in open(CAP, encoding="utf-8")]
print(f"共 {len(recs)} 条记录\n")

groups = collections.defaultdict(list)
for r in recs:
    key = f"{r['method']} {r['url'].split('?')[0]}"
    groups[key].append(r)

SENSITIVE = {"cookie", "authorization", "x-csrf-token", "csrftoken"}

for key, items in groups.items():
    print("=" * 80)
    print(key, f"({len(items)} 次)")
    r = items[0]
    hdrs = {k: v for k, v in (r.get("req_headers") or {}).items()
            if k.lower() not in SENSITIVE and not k.lower().startswith(":")}
    custom = {k: v for k, v in hdrs.items() if k.lower() not in
              ("accept", "accept-encoding", "accept-language", "cache-control",
               "connection", "content-length", "host", "origin", "pragma",
               "referer", "sec-ch-ua", "sec-ch-ua-mobile", "sec-ch-ua-platform",
               "sec-fetch-dest", "sec-fetch-mode", "sec-fetch-site", "user-agent")}
    print("  自定义请求头:", json.dumps(custom, ensure_ascii=False)[:400])
    if r.get("post_data"):
        print("  POST 数据:", r["post_data"][:600])
    body = r.get("resp_body")
    if body:
        try:
            j = json.loads(body)
            if isinstance(j, dict):
                print("  响应 keys:", list(j.keys()))
                # 找列表字段
                for k, v in j.items():
                    if isinstance(v, list) and v:
                        print(f"    列表字段 {k} ({len(v)} 条), 首条 keys:",
                              list(v[0].keys()) if isinstance(v[0], dict) else type(v[0]))
                    elif isinstance(v, dict):
                        print(f"    嵌套 {k}: keys={list(v.keys())}")
                        for k2, v2 in v.items():
                            if isinstance(v2, list) and v2:
                                print(f"      列表 {k}.{k2} ({len(v2)} 条), 首条 keys:",
                                      list(v2[0].keys()) if isinstance(v2[0], dict) else type(v2[0]))
            print("  响应预览:", body[:500])
        except Exception:
            print("  响应(非JSON):", body[:200].replace("\n", " "))
    print()
