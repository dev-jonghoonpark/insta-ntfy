# insta-ntfy

인스타그램 계정(기본값 `@iabstudio`, `@worksout_official`)을 매일 한 번(기본 09:00) 확인해서, 그사이 올라온 새 게시물을 자체 호스팅 ntfy로 보낸다.

- 알림을 누르면 해당 게시물이 열리고, 썸네일이 첨부된다.
- 두 계정이 함께 올린 콜라보 게시물(공동 게시물)은 한 번만 알린다.
- 처음 실행할 때는 기존 게시물을 기록만 하고 알림은 보내지 않는다. 그 뒤 첫 09:00에 그사이 올라온 글이 온다.
- 수집에 실패하면 ntfy로 경고를 보낸다. 일시적인 오류는 1분 간격으로 3번까지 다시 시도한다.

공식 Instagram Graph API의 Business Discovery 기능으로 조회한다.
의존성 없이 Python 3.10+ 표준 라이브러리만 쓴다.

## 세팅

Meta 화면 문구는 자주 바뀌니 아래 메뉴 이름은 대략적인 안내로 보면 된다.

### 1. 내 인스타 계정을 프로페셔널 계정으로 바꾸기

인스타 앱 → 설정 → 계정 유형 및 도구 → 프로페셔널 계정으로 전환 → 크리에이터 또는 비즈니스. 무료이고 부계정을 써도 된다.

### 2. 페이스북 페이지를 만들고 인스타 계정 연결하기

facebook.com에서 페이지를 하나 만든다. 이름은 아무거나 상관없다.
페이지 설정 → 연결된 계정 → Instagram에서 1번 계정을 연결한다.

### 3. Meta 개발자 앱 만들기

1. [developers.facebook.com/apps](https://developers.facebook.com/apps)에서 개발자로 등록한 뒤 앱을 만든다.
2. 사용 사례는 Instagram 관련 항목에서 **Facebook 로그인을 통한 API 설정**을 고른다.
   Instagram 로그인 방식은 Business Discovery를 지원하지 않는다.
   선택지가 다르게 보이면 앱 유형을 "비즈니스"로 만들어도 된다.
3. 앱은 **개발 모드 그대로** 둔다. 내 계정만 쓰는 용도라 앱 검수가 필요 없다.
4. 앱 설정 → 기본 설정에서 **앱 ID**와 **앱 시크릿**을 확인한다.
   앱 시크릿은 앱을 증명하는 비밀번호이고, 아래 액세스 토큰과는 다른 값이다.

### 4. 단기 액세스 토큰 발급 (Graph API 탐색기)

액세스 토큰은 "이 앱이 내 계정 권한으로 API를 호출해도 된다"는 허가증이다. 앱 설정 화면이 아니라 Graph API 탐색기에서 로그인해서 받는다.

1. [Graph API 탐색기](https://developers.facebook.com/tools/explorer/)를 연다.
2. 오른쪽 **Meta 앱** 드롭다운에서 3번 앱을 고른다.
3. **사용자 또는 페이지** 드롭다운은 "사용자 토큰"으로 둔다.
4. **권한 추가**에서 `instagram_basic`, `instagram_manage_insights`, `pages_show_list`, `pages_read_engagement`, `business_management`, `ads_read`를 넣는다.
   `instagram_manage_insights`가 없으면 `(#10) Application does not have permission` 오류가 난다.
   `ads_read`는 페이지를 비즈니스 포트폴리오(Business Manager)로 관리할 때 필요하다.
   목록에 권한이 안 보이면 앱 대시보드 → 이용 사례 → 맞춤 설정에서 해당 권한을 먼저 추가한다.
5. 왼쪽 위 주소가 `graph.facebook.com`인지 확인하고 **Generate Access Token**을 누른다 ("Generate Instagram Access Token"이 아니어야 한다).
   "이전 설정으로 계속하시겠어요?"가 뜨면 **설정 수정**을 누르고, "현재 페이지에만 옵트 인" → 2번 페이지와 1번 인스타 계정을 체크한다.
6. 오른쪽 위 **액세스 토큰** 칸에 `EAA...`로 시작하는 긴 문자열이 생긴다. 이걸 복사한다. 1시간쯤 지나면 만료된다.

### 5. 만료 없는 토큰으로 바꾸기

```sh
python3 setup_meta_token.py
```

앱 ID, 앱 시크릿, 4번 토큰을 차례로 입력하면 `.env`에 넣을 `META_IG_USER_ID`와 `META_ACCESS_TOKEN`이 출력된다.
"토큰 만료: 없음"으로 나오면 정상이다.
페이스북 비밀번호를 바꾸거나 앱 권한을 해제하면 토큰이 무효가 된다. 그때는 수집 실패 알림이 오니 4~5번을 다시 하면 된다.

### 6. .env 작성

```sh
cp .env.example .env
```

`NTFY_URL`, `NTFY_TOPIC`, ntfy 인증 값, 5번에서 나온 두 값을 채운다.

### 7. 감시 대상 계정 확인

Business Discovery는 비즈니스·크리에이터 계정만 조회할 수 있다. 감시 대상이 조회되는지 확인한다.

```sh
set -a; . ./.env; set +a
python3 insta_ntfy.py --check
```

```
✓ @iabstudio (IAB STUDIO): 비즈니스·크리에이터 계정, 게시물 1234개, 팔로워 ...
✗ @someone: 조회 불가 — 개인 계정이거나, 아이디 오타이거나, 토큰 문제입니다.
```

토큰 없이 눈으로 확인하려면 인스타 앱에서 그 프로필을 본다. 이름 아래에 "의류(브랜드)" 같은 카테고리가 보이면 프로페셔널 계정이다.

## 실행

Docker:

```sh
docker compose up -d --build
docker compose logs -f
```

Docker 없이 실행:

```sh
set -a; . ./.env; set +a
python3 insta_ntfy.py            # 계속 떠 있으면서 매일 RUN_AT에 확인
python3 insta_ntfy.py --once     # 한 번만 확인 (cron용)
```

cron을 쓸 경우 (매일 09:00, 서버 시간대 기준):

```
0 9 * * * cd /path/to/insta-ntfy && set -a && . ./.env && python3 insta_ntfy.py --once >> insta-ntfy.log 2>&1
```

알림을 보내지 않고 동작만 확인하려면 `DRY_RUN=1`을 붙인다.

## 환경변수

| 이름 | 기본값 | 설명 |
|---|---|---|
| `NTFY_URL` | (필수) | ntfy 서버 주소. 예: `https://ntfy.example.com` |
| `NTFY_TOPIC` | `instagram` | 발행할 토픽 |
| `NTFY_TOKEN` | | ntfy 액세스 토큰 (`tk_...`) |
| `NTFY_USER` / `NTFY_PASSWORD` | | 토큰 대신 Basic 인증을 쓸 때 |
| `META_IG_USER_ID` | (필수) | 내 인스타 프로페셔널 계정 ID. `setup_meta_token.py`로 얻는다 |
| `META_ACCESS_TOKEN` | (필수) | 만료 없는 페이지 토큰. `setup_meta_token.py`로 얻는다 |
| `META_GRAPH_VERSION` | `v25.0` | Graph API 버전 |
| `IG_USERNAMES` | `iabstudio,worksout_official` | 감시할 계정 (쉼표 구분) |
| `RUN_AT` | `09:00` | 매일 확인할 시각 |
| `TIMEZONE` | `Asia/Seoul` | `RUN_AT`의 시간대 |
| `STATE_FILE` | `state.json` (Docker: `/data/state.json`) | 이미 본 게시물을 기록하는 파일 |
| `DRY_RUN` | `0` | `1`이면 ntfy로 보내지 않고 로그만 남긴다 |

## 한계

- 비즈니스·크리에이터 계정만 감시할 수 있다.
- 계정마다 최근 게시물 50개만 본다. 하루에 50개 넘게 올라오면 일부를 놓친다.
- 하루치를 한꺼번에 보내므로 09:00에 알림이 여러 개 몰려 올 수 있다.
- 스토리는 볼 수 없다. 스토리 알림은 인스타 앱 프로필의 종 아이콘으로 켠다.
