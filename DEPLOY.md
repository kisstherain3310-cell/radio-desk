# 라디오 데스크 — 배포 가이드 (Streamlit Community Cloud)

## 1) 준비

- GitHub 저장소: https://github.com/kisstherain3310-cell/radio-desk
- Main file: `app.py`
- Python 의존성: `requirements.txt`
- API 키는 코드에 넣지 말고 **Secrets**에만 등록

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
```

6. **Deploy** 클릭
7. 완료되면 `https://xxxx.streamlit.app` URL이 생깁니다

## 3) 배포 후 확인 체크리스트

### 필수 (안정화)

- [ ] 피드(CRYPTO / STOCKS)가 로드되는가
- [ ] 상단 배너에 RSS 성공/실패 소스 수가 보이는가
- [ ] 일부 RSS 실패해도 나머지 뉴스는 계속 보이는가
- [ ] 60초 자동갱신 때 화면이 통째로 비지 않는가 (이전 피드 유지)
- [ ] 번역 토글 OFF/ON · 키/할당량 안내 문구 확인
- [ ] Secrets 키를 넣었다면 번역 ON 시 한글이 뜨는가 (할당량 부족이면 안내 문구)

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

## 4) 코드 수정 후 반영

로컬/Cursor에서 수정 → GitHub `main` push  
→ Streamlit Cloud가 자동 redeploy (보통 1~3분)

## 5) 문제 해결

| 증상 | 확인 |
|------|------|
| 앱이 안 뜸 | Cloud 로그, `requirements.txt`, Main file=`app.py` |
| 번역 안 됨 | Secrets `GEMINI_API_KEY`, Gemini 할당량 |
| 피드를 못 가져옴 | Cloud 로그의 RSS/네트워크 오류 |
| 읽기 페이지 404처럼 비움 | `id` 파라미터, RSS에서 해당 링크를 찾는지 |

## 참고

- 로컬: `.env`의 `GEMINI_API_KEY`
- 클라우드: Streamlit **Secrets**의 `GEMINI_API_KEY`
- 현재 읽기 페이지는 query param 프로토타입입니다.
