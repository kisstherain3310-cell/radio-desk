# 라디오 데스크 — 배포 가이드 (Streamlit Community Cloud)

## 1) 준비

- GitHub 저장소: https://github.com/kisstherain3310-cell/radio-desk
- Main file: `app.py`
- Python 의존성: `requirements.txt`
- API 키 등은 코드에 넣지 말고 **Secrets**에만 등록

## 현재 운영 모드 (중요)

이 앱은 지금 **개인이 운영하는 무료 뉴스 단말**입니다.

- **결제(구독)는 사용하지 않습니다.** 사업자등록·토스페이먼츠 가맹이 필요해서, 개인 단계에서는 Pro 월 구독을 받지 않습니다.
- Streamlit Secrets에 `TOSS_CLIENT_KEY` / `TOSS_SECRET_KEY`를 **넣지 마세요.** (넣지 않는 것이 정상입니다.)
- Google 로그인·Supabase도 **필수가 아닙니다.** 번역·RSS만 쓰려면 `GEMINI_API_KEY`만으로 충분합니다.
- 앱의 본체: **검증 매체 RSS 속보 + (선택) 광고 슬롯**
- 앱 내 Gemini 번역 토글은 **숨김** (`SHOW_APP_TRANSLATION_UI = False`). 영어는 Chrome·Edge **주소창 오른쪽 번역** 안내
- 예전에 문서에 있던 Pro/토스 안내는 **나중에 사업자가 생겼을 때를 위한 보관용**이며, 현재 UI에서는 구독·결제를 노출하지 않습니다.
- 코드 스위치: [`billing.py`](billing.py) 의 `ENABLE_PRO_BILLING = False` (사업자 준비 후 `True`로 바꾸면 Pro UI 재노출)

**메시지 원칙:** 번역은 유료 명분이 아님. 현재는 Pro 카피·결제 UI를 쓰지 않습니다.

## 2) Streamlit Cloud에서 앱 만들기

1. 브라우저에서 [https://share.streamlit.io](https://share.streamlit.io) 접속  
   (안 되면 [https://streamlit.io/cloud](https://streamlit.io/cloud))
2. **GitHub 계정으로 로그인** (저장소 권한이 있는 계정)
3. **Create app** / **New app**
4. 설정 예시:
   - Repository: `kisstherain3310-cell/radio-desk`
   - Branch: `main`
   - Main file path: `app.py`
5. **Advanced settings → Secrets** 에 아래 형식으로 입력 후 저장:

```toml
# 개인 운영 · 결제 미사용 — 이것만으로 RSS·번역 동작
GEMINI_API_KEY = "여기에_제미나이_키"

# --- Google Analytics 4 (선택) ---
# GA4 관리 → 데이터 스트림 → 측정 ID (G-XXXXXXXX)
# GA_MEASUREMENT_ID = "G-XXXXXXXX"

# --- Firebase Cloud Messaging 웹 푸시 (선택) ---
# Firebase 콘솔 → 프로젝트 설정 / Cloud Messaging
# FIREBASE_API_KEY = "AIza..."
# FIREBASE_AUTH_DOMAIN = "your-project.firebaseapp.com"
# FIREBASE_PROJECT_ID = "your-project"
# FIREBASE_MESSAGING_SENDER_ID = "123456789"
# FIREBASE_APP_ID = "1:123456789:web:abcd"
# FIREBASE_VAPID_KEY = "BPxxxx..."   # 웹 푸시 인증서(키 쌍) 공개 키

# --- 광고 HTML (선택 · 나중에 붙여넣기) ---
# 비우면 프로토타입 슬롯이 보입니다. 멀티라인이면 ''' ... ''' 사용.
# AD_HTML_HOME_TOP = '''<ins class="adsbygoogle" ...></ins><script>...</script>'''
# AD_HTML_CRYPTO = '''...'''   # (열 상단 광고는 UI에서 비활성 — Secrets만 보관)
# AD_HTML_STOCKS = '''...'''
# AD_HTML_READER_LEFT = '''...'''
# AD_HTML_READER_RIGHT = '''...'''

# --- SIGNALS (이후 · X API 준비되면) ---
# X_BEARER_TOKEN = "AAAA..."

# --- 향후용 Pro (지금은 넣지 않음) ---
# Google 로그인 / Pro 결제용. ENABLE_PRO_BILLING=True 일 때만 의미 있음
# SUPABASE_URL = "https://xxxx.supabase.co"
# SUPABASE_ANON_KEY = "여기에_anon_public_key"
# SUPABASE_SERVICE_ROLE_KEY = "여기에_service_role_key"
# APP_URL = "https://xxxx.streamlit.app"
# TOSS_CLIENT_KEY = "test_ck_..."
# TOSS_SECRET_KEY = "test_sk_..."
```

### GA4 · 웹 푸시 메모

- **GA4:** Secrets에 `GA_MEASUREMENT_ID`만 넣으면 앱 로드 시 `gtag`가 `<head>`에 주입됩니다.
- **FCM:** Secrets에 Firebase 값을 넣고, 저장소의 [`firebase-messaging-sw.js`](firebase-messaging-sw.js) 설정을 채운 뒤 **사이트 루트**(`/firebase-messaging-sw.js`)로 제공해야 백그라운드 알림이 동작합니다. Streamlit Cloud만으로는 SW 서빙이 어려울 수 있어, 커스텀 도메인·정적 호스팅과 함께 쓰는 것을 권장합니다. 프론트는 알림 허용 배너 + 토큰 발급까지 준비되어 있습니다.

6. **Deploy** 클릭
7. 완료되면 `https://xxxx.streamlit.app` URL이 생깁니다

> 향후 Pro를 켤 때: `service_role` 키와 `TOSS_SECRET_KEY`는 **절대** 프론트/공개 저장소에 넣지 마세요. Streamlit Secrets(서버 전용)에만 둡니다.

## 3) 제품 규칙 (현재 · 개인 무료)

| 구분 | 내용 |
|------|------|
| **무료** | 검증된 매체 RSS (코인/주식). 영어는 브라우저 주소창 번역 안내 |
| **광고** | 홈 중앙 1곳 + 읽기 좌·우. Secrets `AD_HTML_*` 있으면 렌더, 없으면 프로토타입 |
| **로그인·결제** | 사용하지 않음 (`ENABLE_PRO_BILLING = False`) |
| **SIGNALS** | 출시 예정 티저. `X_BEARER_TOKEN` 연동은 **이후 스프린트** |

매체 RSS 번역은 무료 편의 기능입니다. 남용 방지를 위한 숨은 일일 soft cap(세션, 약 2,000건)만 있으며 UI에 표시하지 않습니다.

### 3-1) 배포 검증 (개인 모드)

- [ ] 비로그인·결제 Secrets 없이 피드·번역 ON이 동작하는가
- [ ] 사이드바에 「개인 무료 단말 · 로그인·결제 없음」만 보이는가 (구독 버튼 없음)
- [ ] SIGNALS에 월 구독·로그인 유도가 없는가
- [ ] Secrets 없이 배포해도 RSS·번역·광고 슬롯은 동작하는가

## 4) (보관) Google 로그인 — Pro용 · 현재 필수도 업셀도 아님

> **현재 운영 모드에서는 사용하지 않습니다.**  
> 사업자 등록 후 `ENABLE_PRO_BILLING = True` 로 켤 때 참고하세요.

Secrets에 Supabase가 없어도 **매체 RSS·번역·광고 슬롯**은 동작합니다.

### 4-1) Supabase 프로젝트

1. [https://supabase.com](https://supabase.com) 에서 프로젝트 생성
2. **Project Settings → API** 에서 Project URL / `anon` `public` / `service_role` 키 복사 → Streamlit Secrets
3. SQL Editor에서 [`supabase_schema.sql`](supabase_schema.sql) 전체 실행  
   (이미 예전에 실행했다면, `alter table ... toss_*` / `next_billing_at` 과 billing 보호 트리거 부분만 다시 실행해도 됩니다.)

### 4-2) Google Cloud OAuth

1. [Google Cloud Console](https://console.cloud.google.com/) → API 및 서비스 → 사용자 인증 정보
2. **OAuth 클라이언트 ID** (웹 애플리케이션) 생성
3. **승인된 리디렉션 URI**에 Supabase 콜백 추가:

```
https://<PROJECT_REF>.supabase.co/auth/v1/callback
```

4. Client ID / Client Secret 복사

### 4-3) Supabase Auth에 Google 연결

1. Supabase → **Authentication → Providers → Google** 활성화
2. Client ID / Secret 붙여넣기
3. **Authentication → URL Configuration**
   - Site URL: `APP_URL` (Streamlit 앱 주소)
   - Redirect URLs: `APP_URL`, `http://localhost:8501/**` (로컬 테스트용)

## 5) (보관) 토스 Pro — 사업자 있을 때

> **현재 운영 모드에서는 사용하지 않습니다.**  
> 개인·무사업자 단계에서는 Secrets에 토스 키를 넣지 마세요.  
> 사업자 등록·자동결제(빌링) 계약 후 `ENABLE_PRO_BILLING = True` 로 켤 때 참고하세요.

토스는 “구독 Price ID”를 두지 않습니다. **빌링키 발급 → 승인 API로 `amount=3990` 청구** 방식입니다.

Streamlit Cloud에는 크론이 없으므로, **접속/로그인 시 `next_billing_at`이 지났으면 재청구**하는 lazy renewal을 씁니다.  
한동안 앱에 들어오지 않으면 청구가 미뤄질 수 있습니다 (MVP 수용).

### 5-1) 가맹점·자동결제(빌링) 준비

1. [토스페이먼츠](https://www.tosspayments.com/) 가맹점 가입 (사업자)
2. **자동결제(빌링)** 포함 계약/활성화
3. 개발자센터에서 **Client Key** / **Secret Key** 발급  
   - 테스트: `test_ck_...` / `test_sk_...`  
   - 라이브: 검증 후 교체
4. Streamlit Secrets에 `TOSS_CLIENT_KEY`, `TOSS_SECRET_KEY`, `APP_URL`, `SUPABASE_SERVICE_ROLE_KEY` 등록
5. 코드에서 `ENABLE_PRO_BILLING = True`

금액 **3,990원**은 서버가 승인 API에 넣는 값입니다. 대시보드에 별도 상품을 만들 필요는 없습니다.

### 5-2) 결제·콜백 흐름

1. 로그인 → 사이드바 **카드 등록으로 Pro 시작** (토스 빌링 인증창)
2. 성공 시 `APP_URL/?toss=billing&authKey=...&customerKey=...` 로 복귀
3. 서버가 빌링키 발급 → 즉시 3,990원 청구 → `plan=pro`, `next_billing_at = now+30일`
4. 이후 방문 시 `next_billing_at`이 지났으면 동일 금액 재청구 (실패 시 free로 하향)
5. **구독 해지** 버튼으로 빌링키 제거·`plan=free` (앱 내 해지)

실패 콜백: `APP_URL/?toss=fail`

### 5-3) 구독·광고 검증 (Pro 켤 때만)

- [ ] Google 로그인 후 사이드바에 토스 카드 등록 버튼 표시
- [ ] 테스트 카드로 빌링 인증 → `Pro` · 홈/읽기 **광고 숨김**
- [ ] 하단 SIGNALS 티저가 Pro/비Pro에 맞게 보이는가
- [ ] `next_billing_at`을 과거로 두고 접속 시 재청구 시도
- [ ] **구독 해지** → free · 광고 다시 표시
- [ ] 토스 Secrets 없어도 피드·번역·광고 슬롯은 동작

### 5-4) Phase 2 — X 인플루언서·시그널 피드 (별도 착수)

현재는 **출시 예정** 티저만 제공합니다. 코드에 `_load_x_bearer_token()` / `fetch_signals_feed()` 훅만 두었고, **실 API 호출은 하지 않습니다.**  
`X_BEARER_TOKEN`과 유료 X 개발자 플랜이 준비되면 다음 스프린트에서:

1. X API로 인플루언서 타임라인 수집 — Secrets: `X_BEARER_TOKEN`
2. `fetch_signals_feed()`에서 실데이터 반환 → 하단 SIGNALS 영역에 카드 표시
3. 번역·카드 UI는 기존 RSS 파이프라인 재사용
4. 이 문서에 수집 계정 목록·할당량·약관 준수 체크리스트 추가

## 6) 배포 후 확인 체크리스트

### 필수 (안정화)

- [ ] 피드(CRYPTO / STOCKS)가 로드되는가
- [ ] 상단 배너에 RSS 성공/실패 소스 수가 보이는가
- [ ] 일부 RSS 실패해도 나머지 뉴스는 계속 보이는가
- [ ] 60초 자동갱신 때 화면이 통째로 비지 않는가 (이전 피드 유지)
- [ ] 번역 토글 OFF/ON · 키/할당량 안내 문구 확인
- [ ] Secrets 키를 넣었다면 번역 ON 시 한글이 뜨는가 (할당량 부족이면 안내 문구)
- [ ] 카드 시각에 `KST` 표기가 있는가
- [ ] 구독·로그인 업셀이 보이지 않는가 (개인 모드)

### 홈·읽기 광고 슬롯 (꼭)

- [ ] 홈: 배너 아래 + CRYPTO 상단 + STOCKS 상단 슬롯 3곳
- [ ] 헤드라인 클릭 → 읽기 페이지 (`?view=read&id=...`)
- [ ] 읽기: 가운데 제목·번역, 좌·우 Ad 슬롯
- [ ] **원문 보기**만 외부로 이동 · **목록으로** 복귀
- [ ] 60초 자동갱신과 광고 강제 리프레시를 연동하지 않았는가

### 광고 네트워크 연동 시 (Secrets `AD_HTML_*`)

슬롯 키:

| Secrets 키 | 위치 |
|------------|------|
| `AD_HTML_HOME_TOP` | 홈 상단 (배너 아래) |
| `AD_HTML_CRYPTO` | CRYPTO 열 상단 |
| `AD_HTML_STOCKS` | STOCKS 열 상단 |
| `AD_HTML_READER_LEFT` | 읽기 페이지 왼쪽 |
| `AD_HTML_READER_RIGHT` | 읽기 페이지 오른쪽 |

- [ ] 우리 도메인 페이지에만 광고 코드 삽입
- [ ] 원문 iframe + 주변 광고 금지
- [ ] 자동갱신과 광고 강제 리프레시 연동 금지 (앱은 슬롯 HTML만 렌더)

## 7) 코드 수정 후 반영

로컬/Cursor에서 수정 → GitHub `main` push  
→ Streamlit Cloud가 자동 redeploy (보통 1~3분)

## 8) 문제 해결

| 증상 | 확인 |
|------|------|
| 앱이 안 뜸 | Cloud 로그, `requirements.txt`, Main file=`app.py` |
| 번역 안 됨 | Secrets `GEMINI_API_KEY`, Gemini 할당량 |
| 피드를 못 가져옴 | Cloud 로그의 RSS/네트워크 오류 |
| 읽기 페이지 404처럼 비움 | `id` 파라미터, RSS에서 해당 링크를 찾는지 |
| 구독 버튼이 보임 | `billing.ENABLE_PRO_BILLING` 이 `False`인지 확인 |
| (보관) Google 로그인 실패 | `APP_URL`·Supabase Redirect URLs·Google 리디렉션 URI |
| (보관) 결제 후 Pro 안 됨 | `ENABLE_PRO_BILLING=True`, `SUPABASE_SERVICE_ROLE_KEY`, `TOSS_*`, `APP_URL` |

## 참고

- 로컬: `.env`에 위 Secrets와 동일한 키
- 클라우드: Streamlit **Secrets**
- 현재 읽기 페이지는 query param 프로토타입입니다.
