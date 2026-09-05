# -*- coding: utf-8 -*-
"""分析华为抓包：create/query 的请求格式和鉴权头"""
import json, pathlib

CAP = pathlib.Path(__file__).parent / "capture_huawei.jsonl"
recs = [json.loads(l) for l in open(CAP, encoding="utf-8")]

SENSITIVE_COOKIES = True

for r in recs:
    if "notepad" not in r["url"] or r["url"].endswith(".png"):
        continue
    print("=" * 80)
    print(r["method"], r["url"])
    hdrs = r.get("req_headers") or {}
    for k, v in hdrs.items():
        kl = k.lower()
        if kl == "cookie":
            names = [c.split("=")[0].strip() for c in v.split(";")]
            print("  cookie keys:", names)
        elif kl.startswith(("x-", "csrf")) or kl in ("authorization", "device-id", "content-type"):
            print(f"  {k}: {v[:150]}")
    if r.get("post_data"):
        print("  POST:", r["post_data"][:1500])
    if r.get("resp_body"):
        print("  RESP:", r["resp_body"][:1500])
    print()
