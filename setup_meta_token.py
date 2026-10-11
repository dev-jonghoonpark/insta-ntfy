#!/usr/bin/env python3
"""Graph API 탐색기에서 받은 단기 토큰을 만료 없는 페이지 토큰으로 바꾸고 IG 사용자 ID를 찾는다.

사용법:
    python3 setup_meta_token.py
앱 ID, 앱 시크릿, 단기 사용자 토큰을 차례로 입력하면 .env에 넣을 값을 출력한다.
"""

from __future__ import annotations

import getpass
import json
import os
import sys
import urllib.error
import urllib.parse
import urllib.request

VERSION = os.environ.get("META_GRAPH_VERSION", "v25.0")


def graph(path: str, **params) -> dict:
    url = f"https://graph.facebook.com/{VERSION}/{path}?{urllib.parse.urlencode(params)}"
    try:
        with urllib.request.urlopen(url, timeout=30) as resp:
            return json.loads(resp.read())
    except urllib.error.HTTPError as e:
        sys.exit(f"Graph API 오류 ({path}): {e.read().decode('utf-8', 'replace')}")


def main() -> None:
    app_id = input("앱 ID: ").strip()
    app_secret = getpass.getpass("앱 시크릿 (입력 내용은 표시되지 않음): ").strip()
    short_token = getpass.getpass("Graph API 탐색기의 사용자 액세스 토큰: ").strip()

    # 1) 단기 사용자 토큰(약 1시간) → 장기 사용자 토큰(약 60일)
    long_user = graph(
        "oauth/access_token",
        grant_type="fb_exchange_token",
        client_id=app_id,
        client_secret=app_secret,
        fb_exchange_token=short_token,
    )["access_token"]

    # 2) 장기 사용자 토큰으로 받은 페이지 토큰은 만료되지 않는다.
    pages = graph(
        "me/accounts",
        fields="name,access_token,instagram_business_account{id,username}",
        access_token=long_user,
    ).get("data", [])
    linked = [p for p in pages if p.get("instagram_business_account")]
    if not linked:
        sys.exit(
            "인스타그램 계정이 연결된 페이스북 페이지를 찾지 못했습니다.\n"
            "페이지에 프로페셔널 계정을 연결했는지, 토큰 발급 시 해당 페이지를 선택했는지 확인하세요."
        )

    for page in linked:
        ig = page["instagram_business_account"]
        info = graph("debug_token", input_token=page["access_token"], access_token=f"{app_id}|{app_secret}")
        expires = info.get("data", {}).get("expires_at", 0)
        print(f"\n# 페이지 '{page['name']}' ↔ @{ig.get('username')}")
        print(f"# 토큰 만료: {'없음' if not expires else expires}")
        print(f"META_IG_USER_ID={ig['id']}")
        print(f"META_ACCESS_TOKEN={page['access_token']}")


if __name__ == "__main__":
    main()
