#!/usr/bin/env python3
"""Download PDF from arxiv by arxiv_id.

用法: download_arxiv_pdf.py <arxiv_id> <out_dir>
产出: <out_dir>/paper.pdf

支持版本回退（v1 → 无版本），User-Agent 防 arxiv 屏蔽，3 次重试。
"""
import os
import sys
import time
import urllib.request

UA = "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 paper-preread/1.0"


def fetch(url, retries=3):
    last = None
    for i in range(retries):
        try:
            req = urllib.request.Request(url, headers={"User-Agent": UA})
            with urllib.request.urlopen(req, timeout=60) as r:
                return r.read(), dict(r.headers)
        except Exception as e:
            last = e
            time.sleep(2 ** i)
    raise RuntimeError(f"failed after {retries} retries: {url}\n{last}")


def main():
    aid = sys.argv[1].strip()
    outdir = sys.argv[2]
    os.makedirs(outdir, exist_ok=True)

    # arxiv ID 可能是 2409.18839 或 2409.18839v2；尝试多个 URL
    base_id = aid.replace("v", "").rsplit(".", 1)
    arxiv_id = aid if "." in aid and "v" in aid.split(".")[-1] else aid

    candidates = [
        f"https://arxiv.org/pdf/{arxiv_id}",
        f"https://arxiv.org/pdf/{arxiv_id}v1",
        f"https://export.arxiv.org/pdf/{arxiv_id}",
    ]

    for url in candidates:
        try:
            data, headers = fetch(url)
            if data[:5] == b"%PDF-":
                with open(os.path.join(outdir, "paper.pdf"), "wb") as f:
                    f.write(data)
                size_mb = len(data) / 1024 / 1024
                print(f"✓ {aid}: {size_mb:.1f} MB from {url}")
                print(f"  → {outdir}/paper.pdf")
                return
        except Exception as e:
            print(f"  skip {url}: {e}")
    sys.exit(f"ERROR: could not download {aid} from any candidate URL")


if __name__ == "__main__":
    main()