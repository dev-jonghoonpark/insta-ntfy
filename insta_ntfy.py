#!/usr/bin/env python3
"""Instagram 계정에 새 게시물이 올라오면 ntfy로 알림을 보낸다.

공식 Instagram Graph API의 Business Discovery로 조회하므로
감시 대상은 비즈니스·크리에이터 계정이어야 한다. 표준 라이브러리만 사용한다. 설정은 전부 환경변수로 받는다 (README 참고).
"""

from __future__ import annotations

import json
import logging
import os
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

log = logging.getLogger("insta-ntfy")

# 하루 한 번 확인하므로 한 번에 넉넉히 가져온다. worksout 기준 약 두 달 치.
MEDIA_LIMIT = 50
# 계정당 기억해 둘 shortcode 수. MEDIA_LIMIT보다 커야 한다.
MAX_SEEN_PER_ACCOUNT = 500
FETCH_ATTEMPTS = 3
RETRY_DELAY_SECONDS = 60


def env(name: str, default: str | None = None) -> str | None:
    value = os.environ.get(name, "").strip()
    return value or default


class Config:
    def __init__(self) -> None:
        self.usernames = [
            u.strip().lstrip("@")
            for u in env("IG_USERNAMES", "iabstudio,worksout_official").split(",")
            if u.strip()
        ]
        self.graph_token = env("META_ACCESS_TOKEN")
        self.graph_ig_user_id = env("META_IG_USER_ID")
        self.graph_version = env("META_GRAPH_VERSION", "v25.0")
        self.ntfy_url = (env("NTFY_URL") or "").rstrip("/")
        self.ntfy_topic = env("NTFY_TOPIC", "instagram")
        self.ntfy_token = env("NTFY_TOKEN")
        self.ntfy_user = env("NTFY_USER")
        self.ntfy_password = env("NTFY_PASSWORD")
        self.state_file = Path(env("STATE_FILE", "state.json"))
        hour, minute = env("RUN_AT", "09:00").split(":")
        self.run_at = (int(hour), int(minute))
        self.tz = ZoneInfo(env("TIMEZONE", "Asia/Seoul"))
        self.dry_run = env("DRY_RUN", "0") == "1"

        if not self.ntfy_url and not self.dry_run:
            sys.exit("NTFY_URL 환경변수가 필요합니다 (예: https://ntfy.example.com)")
        if not (self.graph_token and self.graph_ig_user_id):
            sys.exit("META_ACCESS_TOKEN과 META_IG_USER_ID가 필요합니다 (setup_meta_token.py로 발급)")


# ---------------------------------------------------------------- state


def load_state(path: Path) -> dict:
    if path.exists():
        return json.loads(path.read_text())
    return {"accounts": {}}


def save_state(path: Path, state: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(state, ensure_ascii=False, indent=2))
    tmp.replace(path)


# ---------------------------------------------------------------- instagram


class FetchError(Exception):
    pass


GRAPH_MEDIA_FIELDS = "id,caption,media_type,media_url,thumbnail_url,permalink,timestamp"


def business_discovery(cfg: Config, username: str, fields: str) -> dict:
    """대상 계정의 business_discovery 노드를 돌려준다."""
    query = urllib.parse.urlencode(
        {"fields": f"business_discovery.username({username}){{{fields}}}", "access_token": cfg.graph_token}
    )
    url = f"https://graph.facebook.com/{cfg.graph_version}/{cfg.graph_ig_user_id}?{query}"
    try:
        with urllib.request.urlopen(url, timeout=30) as resp:
            body = json.loads(resp.read())
    except urllib.error.HTTPError as e:
        try:
            err = json.loads(e.read())["error"]
            detail = f"code={err.get('code')} {err.get('message')}"
        except (ValueError, KeyError):
            detail = ""
        raise FetchError(f"@{username}: Graph API HTTP {e.code} {detail}") from e
    except (urllib.error.URLError, TimeoutError) as e:
        raise FetchError(f"@{username}: {e}") from e

    if "business_discovery" not in body:
        raise FetchError(f"@{username}: 예상과 다른 응답 {str(body)[:200]}")
    return body["business_discovery"]


def fetch_posts(cfg: Config, username: str) -> list[dict]:
    """프로필의 최근 게시물을 최신순으로 돌려준다. 일시적인 오류는 몇 번 재시도한다."""
    for attempt in range(1, FETCH_ATTEMPTS + 1):
        try:
            node = business_discovery(cfg, username, f"media.limit({MEDIA_LIMIT}){{{GRAPH_MEDIA_FIELDS}}}")
            break
        except FetchError as e:
            if attempt == FETCH_ATTEMPTS:
                raise
            log.warning("%s (재시도 %d/%d)", e, attempt, FETCH_ATTEMPTS - 1)
            time.sleep(RETRY_DELAY_SECONDS)
    return [parse_graph_media(n) for n in node.get("media", {}).get("data", [])]


def parse_graph_media(node: dict) -> dict:
    # 콜라보 공동 게시물은 계정마다 media id가 다를 수 있어 permalink의 shortcode를 키로 쓴다.
    permalink = node.get("permalink", "")
    shortcode = permalink.rstrip("/").rsplit("/", 1)[-1] or node["id"]
    ts = node.get("timestamp", "")
    try:
        timestamp = int(datetime.strptime(ts, "%Y-%m-%dT%H:%M:%S%z").timestamp())
    except ValueError:
        timestamp = 0
    return {
        "shortcode": shortcode,
        "caption": node.get("caption", ""),
        # 동영상은 media_url이 영상 파일이라 썸네일을 우선한다.
        "thumbnail": node.get("thumbnail_url") or node.get("media_url"),
        "timestamp": timestamp,
        "is_video": node.get("media_type") == "VIDEO",
        "permalink": permalink,
    }


# ---------------------------------------------------------------- ntfy


def ntfy_publish(cfg: Config, title: str, message: str, **extra) -> None:
    # JSON 발행 방식을 써야 제목/본문의 한글이 헤더 인코딩 문제 없이 전달된다.
    payload = {"topic": cfg.ntfy_topic, "title": title, "message": message, **extra}
    if cfg.dry_run:
        log.info("[dry-run] ntfy %s", json.dumps(payload, ensure_ascii=False))
        return

    headers = {"Content-Type": "application/json"}
    if cfg.ntfy_token:
        headers["Authorization"] = f"Bearer {cfg.ntfy_token}"
    elif cfg.ntfy_user and cfg.ntfy_password:
        import base64

        cred = base64.b64encode(f"{cfg.ntfy_user}:{cfg.ntfy_password}".encode()).decode()
        headers["Authorization"] = f"Basic {cred}"

    req = urllib.request.Request(
        cfg.ntfy_url,
        data=json.dumps(payload).encode(),
        headers=headers,
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=30) as resp:
        resp.read()


def notify_post(cfg: Config, username: str, post: dict) -> None:
    caption = post["caption"].strip()
    kind = "릴스" if post["is_video"] else "게시물"
    message = caption[:500] + ("…" if len(caption) > 500 else "") or "(본문 없음)"
    extra = {
        "click": post.get("permalink") or f"https://www.instagram.com/p/{post['shortcode']}/",
        "tags": ["camera_flash", username],
    }
    if post["thumbnail"]:
        extra["attach"] = post["thumbnail"]
        extra["filename"] = f"{post['shortcode']}.jpg"
    ntfy_publish(cfg, f"@{username} 새 {kind}", message, **extra)


# ---------------------------------------------------------------- main loop


def check_once(cfg: Config) -> None:
    state = load_state(cfg.state_file)
    accounts = state.setdefault("accounts", {})
    # 콜라보 게시물은 두 계정에 동시에 뜨므로 계정 구분 없이 한 번만 알린다.
    seen_anywhere = {sc for seen in accounts.values() for sc in seen}
    errors = []

    for username in cfg.usernames:
        try:
            posts = fetch_posts(cfg, username)
        except FetchError as e:
            log.warning("%s", e)
            errors.append(str(e))
            continue

        first_run = username not in accounts
        seen = accounts.setdefault(username, [])
        new_posts = [p for p in posts if p["shortcode"] not in seen]

        if first_run:
            log.info("@%s 첫 실행: 기존 게시물 %d개를 기록만 하고 알림은 보내지 않음", username, len(posts))
        else:
            # 오래된 것부터 보내야 알림 순서가 자연스럽다.
            for post in sorted(new_posts, key=lambda p: p["timestamp"]):
                if post["shortcode"] in seen_anywhere:
                    log.info("@%s %s 다른 계정에서 이미 알림", username, post["shortcode"])
                    continue
                log.info("@%s 새 게시물 %s", username, post["shortcode"])
                notify_post(cfg, username, post)
                seen_anywhere.add(post["shortcode"])

        seen[:0] = [p["shortcode"] for p in new_posts]
        del seen[MAX_SEEN_PER_ACCOUNT:]
        save_state(cfg.state_file, state)  # 알림 직후 바로 저장해 중복 알림을 막는다

    # 토큰 만료 등으로 실패하면 조용히 놓치지 않도록 매번 경고한다.
    if errors:
        ntfy_publish(
            cfg,
            "insta-ntfy 수집 실패",
            "META_ACCESS_TOKEN이 무효가 됐는지 확인하세요.\n" + "\n".join(errors),
            tags=["warning"],
        )


def check_accounts(cfg: Config) -> int:
    """감시 대상이 Business Discovery로 조회 가능한(비즈니스·크리에이터) 계정인지 확인한다."""
    ok = True
    for username in cfg.usernames:
        try:
            info = business_discovery(cfg, username, "username,name,followers_count,media_count")
        except FetchError as e:
            ok = False
            print(f"✗ @{username}: 조회 불가 — 개인 계정이거나, 아이디 오타이거나, 토큰 문제입니다.\n  {e}")
            continue
        print(
            f"✓ @{username} ({info.get('name', '')}): 비즈니스·크리에이터 계정, "
            f"게시물 {info.get('media_count')}개, 팔로워 {info.get('followers_count')}명"
        )
    return 0 if ok else 1


def main() -> None:
    logging.basicConfig(
        level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s", stream=sys.stdout
    )
    cfg = Config()

    if "--check" in sys.argv:
        sys.exit(check_accounts(cfg))
    if "--once" in sys.argv:
        check_once(cfg)
        return

    log.info("감시 시작: %s (매일 %02d:%02d)", ", ".join("@" + u for u in cfg.usernames), *cfg.run_at)
    # 기준점이 없으면 바로 한 번 돌려 기존 게시물을 기록해 둔다. 그래야 첫 알림 시각에 그 이후 글만 온다.
    if not load_state(cfg.state_file).get("accounts"):
        run_safely(cfg)
    while True:
        next_run = next_run_time(cfg, datetime.now(cfg.tz))
        log.info("다음 확인: %s", next_run.strftime("%Y-%m-%d %H:%M %Z"))
        sleep_until(next_run, cfg.tz)
        run_safely(cfg)


def run_safely(cfg: Config) -> None:
    try:
        check_once(cfg)
    except Exception:
        log.exception("확인 중 예외 발생")


def next_run_time(cfg: Config, now: datetime) -> datetime:
    hour, minute = cfg.run_at
    target = now.replace(hour=hour, minute=minute, second=0, microsecond=0)
    return target if target > now else target + timedelta(days=1)


def sleep_until(target: datetime, tz: ZoneInfo) -> None:
    # 서버 시계가 조정되거나 절전에서 깨어나도 어긋나지 않도록 짧게 나눠 잔다.
    while (remaining := (target - datetime.now(tz)).total_seconds()) > 0:
        time.sleep(min(remaining, 300))


if __name__ == "__main__":
    main()
