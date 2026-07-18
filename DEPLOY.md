# 라디오 데스크 — 배포 가이드 (Streamlit Community Cloud)

## 1) 준비

- GitHub 저장소: https://github.com/kisstherain3310-cell/radio-desk
- Main file: `app.py`
- Python 의존성: `requirements.txt`
- API 키·Supabase·Stripe 값은 코드에 넣지 말고 **Secrets**에만 등록

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
GEMINI_API_KEY = "여기에_제미나이_키"

# Google 로그인 + 일일 번역 쿼터 (없으면 세션 맛보기 10건만 동작)
SUPABASE_URL = "https://xxxx.supabase.co"
SUPABASE_ANON_KEY = "여기에_anon_public_key"
SUPABASE_SERVICE_ROLE_KEY = "여기에_service_role_key"
APP_URL = "https://xxxx.streamlit.app"

# Stripe Pro 구독 월 2,990원 (없으면 구독 버튼만 비활성)
STRIPE_SECRET_KEY = "sk_test_..."
STRIPE_PRICE_ID = "price_..."
```

6. **Deploy** 클릭
7. 완료되면 `https://xxxx.streamlit.app` URL이 생깁니다  
   → 그 URL을 Secrets의 `APP_URL`과 아래 Google/Supabase/Stripe redirect에 넣으세요.

> `service_role` 키는 **절대** 프론트/공개 저장소에 넣지 마세요. Streamlit Secrets(서버 전용)에만 둡니다.

## 3) Google 로그인 + 일일 쿼터 (Supabase)

Secrets에 Supabase가 없으면 앱은 죽지 않고 **비로그인 세션 맛보기(10건)** 만 동작합니다.

### 3-1) Supabase 프로젝트

1. [https://supabase.com](https://supabase.com) 에서 프로젝트 생성
2. **Project Settings → API** 에서 Project URL / `anon` `public` / `service_role` 키 복사 → Streamlit Secrets
3. SQL Editor에서 [`supabase_schema.sql`](supabase_schema.sql) 전체 실행  
   (이미 예전에 실행했다면, 파일 안의 `alter table ... stripe_*` 와 billing 보호 트리거 부분만 다시 실행해도 됩니다.)

### 3-2) Google Cloud OAuth

1. [Google Cloud Console](https://console.cloud.google.com/) → API 및 서비스 → 사용자 인증 정보
2. **OAuth 클라이언트 ID** (웹 애플리케이션) 생성
3. **승인된 리디렉션 URI**에 Supabase 콜백 추가:

```
https://<PROJECT_REF>.supabase.co/auth/v1/callback
```

4. Client ID / Client Secret 복사

### 3-3) Supabase Auth에 Google 연결

1. Supabase → **Authentication → Providers → Google** 활성화
2. Client ID / Secret 붙여넣기
3. **Authentication → URL Configuration**
   - Site URL: `APP_URL` (Streamlit 앱 주소)
   - Redirect URLs: `APP_URL`, `http://localhost:8501/**` (로컬 테스트용)

### 3-4) 동작 규칙

| 상태 | 번역 한도 | 리셋 |
|------|-----------|------|
| 비로그인 | 세션당 10건 | 세션 종료 |
| Google 로그인 (free) | 하루 30건 | KST 자정 |
| Pro 구독 | 무제한 | Stripe 구독 유지 시 |

캐시 히트는 차감하지 않습니다.

### 3-5) 로그인·쿼터 검증

- [ ] 사이드바에 **Google로 로그인** 버튼이 보이는가 (Secrets 있을 때)
- [ ] 로그인 후 이메일·**오늘 잔여 n/30** 이 보이는가
- [ ] 새로고침 후에도 로그인 유지되는가
- [ ] 번역 ON 시 일일 잔여가 줄고, 캐시 히트는 안 주는가
- [ ] Secrets 없이 배포해도 피드·세션 맛보기만으로 동작하는가

## 4) Stripe Pro 구독 (월 2,990원 KRW)

Streamlit Cloud에는 웹훅 서버가 없으므로, **Checkout 성공 콜백 + 로그인 시 Stripe API 동기화**로 `profiles.plan` 을 맞춥니다.

### 4-1) Stripe 상품 만들기

1. [Stripe Dashboard](https://dashboard.stripe.com/) (테스트 모드 권장)
2. **Product** 생성: 이름 예) `라디오 데스크 Pro`
3. **Price**: Recurring · **KRW 2,990 / month**
4. Price ID (`price_...`) 복사 → Secrets `STRIPE_PRICE_ID`
5. Developers → API keys → Secret key → `STRIPE_SECRET_KEY`

### 4-2) Customer Portal (해지·카드 변경)

1. Stripe → Settings → Billing → Customer portal
2. 구독 해지·결제 수단 변경 허용
3. 앱의 **구독 관리** 버튼이 이 포털로 이동합니다

### 4-3) 구독 검증

- [ ] Google 로그인 후 **Pro 구독 · 월 2,990원** 버튼 표시
- [ ] Checkout(테스트 카드 `4242…`) 완료 → 앱으로 복귀 → `번역 무제한 (Pro)`
- [ ] 번역 ON 해도 잔여가 줄지 않음
- [ ] **구독 관리**에서 해지 후 동기화(최대 약 5분 또는 재로그인) → free · 하루 30건
- [ ] Stripe Secrets 없어도 피드·로그인·일일 쿼터는 동작

### 4-4) 후속(선택): Edge Function 웹훅

실시간 해지 반영이 필요하면 Supabase Edge Function으로 Stripe webhook을 받는 구성을 추가할 수 있습니다. MVP에서는 API 동기화로 충분합니다.

## 5) 배포 후 확인 체크리스트

### 필수 (안정화)

- [ ] 피드(CRYPTO / STOCKS)가 로드되는가
- [ ] 상단 배너에 RSS 성공/실패 소스 수가 보이는가
- [ ] 일부 RSS 실패해도 나머지 뉴스는 계속 보이는가
- [ ] 60초 자동갱신 때 화면이 통째로 비지 않는가 (이전 피드 유지)
- [ ] 번역 토글 OFF/ON · 키/할당량 안내 문구 확인
- [ ] Secrets 키를 넣었다면 번역 ON 시 한글이 뜨는가 (할당량 부족이면 안내 문구)
- [ ] 카드 시각에 `KST` 표기가 있는가

### 읽기 페이지 + 광고 슬롯 (꼭)

- [ ] 헤드라인 클릭 → 읽기 페이지 (`?view=read&id=...`)
- [ ] 가운데 제목·번역, 좌·우 Ad 슬롯
- [ ] **원문 보기**만 외부로 이동
- [ ] **목록으로** 복귀
- [ ] 읽기 URL 새로고침 후에도 기사가 다시 찾아지는가

### 광고 네트워크 연동 시 (나중)

- [ ] 우리 도메인 페이지에만 광고 코드
- [ ] 원문 iframe + 주변 광고 금지
- [ ] 자동갱신과 광고 리프레시 연동 금지

## 6) 코드 수정 후 반영

로컬/Cursor에서 수정 → GitHub `main` push  
→ Streamlit Cloud가 자동 redeploy (보통 1~3분)

## 7) 문제 해결

| 증상 | 확인 |
|------|------|
| 앱이 안 뜸 | Cloud 로그, `requirements.txt`, Main file=`app.py` |
| 번역 안 됨 | Secrets `GEMINI_API_KEY`, Gemini 할당량 |
| 피드를 못 가져옴 | Cloud 로그의 RSS/네트워크 오류 |
| 읽기 페이지 404처럼 비움 | `id` 파라미터, RSS에서 해당 링크를 찾는지 |
| Google 로그인 실패 | `APP_URL`·Supabase Redirect URLs·Google 리디렉션 URI |
| 로그인 후 잔여가 안 보임 | `supabase_schema.sql` 실행 여부, RLS, anon key |
| 결제 후 Pro 안 됨 | `SUPABASE_SERVICE_ROLE_KEY`, `STRIPE_*`, Checkout success URL의 `APP_URL` |
| 해지 후에도 Pro | 최대 5분 대기 또는 로그아웃 후 재로그인(동기화) |

## 참고

- 로컬: `.env`에 위 Secrets와 동일한 키
- 클라우드: Streamlit **Secrets**
- 현재 읽기 페이지는 query param 프로토타입입니다.
