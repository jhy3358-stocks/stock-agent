# 주식 에이전트팀

매일 아침 국내/미국 주요 종목·지수의 기술적 분석 리포트를 자동 생성해 카카오톡 "나에게 보내기"로 발송합니다.
(요구사항 원문: `주식에이전트팀_요구사항-2.md`)

## 구성
- `config.py` — 추적 대상 종목/지수 정의
- `src/kr_stocks.py` — 국내 종목 데이터 수집 (pykrx)
- `src/us_stocks.py` — 미국 종목 및 지수(코스피/나스닥/S&P500) 데이터 수집 (yfinance)
  - 참고: pykrx의 코스피 지수 조회 API가 KRX 서버 세션 문제로 현재 불안정하여, 지수는 코스피 포함 전부
    yfinance(`^KS11`, `^IXIC`, `^GSPC`)로 수집합니다. 개별 국내 종목은 pykrx를 그대로 사용합니다.
- `src/indicators.py` — 이동평균(5/20/60일), RSI(14일), 거래량 증감 계산
- `src/report.py` — 콘솔용 전체 리포트 텍스트 + 카카오톡 요약 메시지(200자 이내) 생성
- `src/html_report.py` — GitHub Pages에 게시할 전체 상세 리포트 HTML 페이지 생성 (공시/뉴스/의견 코멘트 포함)
- `src/dart_client.py` — 국내 종목 최근 공시 수집 (OpenDART Open API, 무료 인증키 필요)
- `src/sec_client.py` — 미국 종목 최근 공시 수집 (SEC EDGAR, API 키 불필요)
- `src/news_client.py` — 미국 종목 관련 뉴스 수집 (Yahoo Finance `yfinance.news`, Seeking Alpha 공개 RSS — 둘 다 로그인 불필요)
- `src/naver_news_client.py` — 국내 종목 관련 뉴스 수집 (네이버 뉴스 검색 API, 무료 인증키 필요)
- `src/signal.py` — RSI/이동평균을 조합한 규칙 기반 매수/매도 관점 코멘트 (애널리스트 의견 아님, 참고용)
- `src/kakao_client.py` — 카카오톡 "나에게 보내기" 발송 (REST API 직접 호출)
- `src/main.py` — 전체 파이프라인 실행 진입점
- `scripts/kakao_auth_setup.py` — 최초 1회 실행하는 카카오 OAuth 인증 스크립트
- `.github/workflows/daily_report.yml` — 매일 06:00 KST 자동 실행 (GitHub Actions)

## 발송 방식

카카오톡 기본 텍스트 템플릿은 1건당 200자 제한이 있어 15개 종목의 상세 내용을 다 담을 수 없습니다.
그래서 카카오톡에는 **지수 등락률 + 상승/하락 상위 종목 요약 메시지 1건**만 보내고, 종목별 상세(현재가/이동평균/RSI/거래량)는
`docs/index.html`로 생성해 **GitHub Pages**에 자동 게시한 뒤 그 URL을 요약 메시지 본문에 텍스트로 포함시킵니다.
(카카오 앱이 메시지 API 검수 전에는 템플릿의 `button_title`/`link` 버튼이 렌더링되지 않아, 대신 카카오톡이
자동으로 링크화하는 일반 URL 텍스트를 본문에 직접 넣는 방식을 사용합니다.)

## 1. 로컬 환경 설정

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env
```

## 2. 카카오 디벨로퍼스 앱 생성 (최초 1회, 사용자가 직접 진행)

1. https://developers.kakao.com 접속 → 로그인 → **내 애플리케이션** → **애플리케이션 추가하기**
2. 앱 생성 후 **앱 키** 메뉴에서 **REST API 키** 복사 → `.env`의 `KAKAO_REST_API_KEY`에 붙여넣기
3. **카카오 로그인** 메뉴에서 활성화 ON
4. **카카오 로그인 > Redirect URI**에 다음 URL 등록 (카카오에서 제공하는 테스트용 리다이렉트, 별도 서버 불필요):
   `https://developers.kakao.com/tool/oauth`
5. **카카오 로그인 > 동의항목**에서 "카카오톡 메시지 전송" 항목을 **필수 동의**로 설정
   (scope 이름: `talk_message` — "나에게 보내기"는 별도 검수 없이 바로 사용 가능)
6. `.env`의 `KAKAO_REDIRECT_URI`가 4번 값과 동일한지 확인 (기본값 그대로 사용해도 무방)

## 3. refresh_token 발급 (최초 1회)

```bash
python scripts/kakao_auth_setup.py
```

- 출력된 인가 URL을 브라우저에서 열고 로그인/동의
- 리다이렉트된 페이지 URL의 `code=` 뒤 값을 복사해 터미널에 붙여넣기
- 발급된 `refresh_token`이 `.kakao_token.json`에 저장되고, GitHub Secrets에 등록할 값이 콘솔에 출력됨
- 로컬 테스트를 위해 `.env`의 `KAKAO_REFRESH_TOKEN`에도 같은 값을 채워두면 4번 단계에서 실제 발송까지 확인 가능

## 3-1. DART 인증키 발급 (국내 공시 조회용, 선택)

1. https://opendart.fss.or.kr 회원가입/로그인
2. **인증키 신청/관리** 메뉴에서 인증키 발급 신청 (즉시 무료 발급)
3. 발급된 인증키를 `.env`의 `DART_API_KEY`에 붙여넣기

키가 없어도 파이프라인은 정상 동작하며, 이 경우 국내 종목 공시만 생략됩니다 (미국 SEC 공시는 키 없이 항상 조회됨).

## 3-2. 네이버 뉴스 검색 API 발급 (국내 종목 뉴스 조회용, 선택)

1. https://developers.naver.com 접속 → 로그인 → **Application > 애플리케이션 등록**
2. 사용 API에서 **검색** 체크, WEB 서비스 URL은 형식적 필드이므로 아무 URL이나 입력
3. 등록 후 발급된 **Client ID**, **Client Secret**을 `.env`의 `NAVER_CLIENT_ID`, `NAVER_CLIENT_SECRET`에 붙여넣기

키가 없어도 파이프라인은 정상 동작하며, 이 경우 국내 종목 뉴스만 생략됩니다.

## 4. 로컬 테스트

```bash
python -m src.main
```

- `.env`에 카카오 값이 없으면 리포트를 콘솔에만 출력하고 발송은 건너뜁니다 (데이터 수집/지표 계산 검증용)
- `.env`에 `KAKAO_REST_API_KEY`, `KAKAO_REFRESH_TOKEN`을 모두 채우면 실제로 카카오톡 요약 메시지 발송까지 수행합니다
- 실행할 때마다 `docs/index.html`이 갱신됩니다 (상세 리포트 페이지)
- 로컬에서 카카오톡 메시지에 실제 GitHub Pages 링크를 넣어보고 싶다면 `.env`에 `REPORT_PAGE_URL`을 추가하세요
  (5번에서 Pages를 활성화한 뒤의 URL). 비워두면 임시로 `https://github.com`이 사용됩니다.

## 5. GitHub 저장소 연결, Pages 활성화, 스케줄 등록

1. GitHub에 새 저장소 생성 후 본 프로젝트를 push
2. 저장소 **Settings > Secrets and variables > Actions**에서 Secret 추가:
   - `KAKAO_REST_API_KEY`
   - `KAKAO_REFRESH_TOKEN`
   - `DART_API_KEY` (선택 — 없으면 국내 공시 조회만 생략됨)
   - `NAVER_CLIENT_ID`, `NAVER_CLIENT_SECRET` (선택 — 없으면 국내 뉴스 조회만 생략됨)
3. 저장소 **Settings > Pages**에서 Source를 **Deploy from a branch**로 설정하고,
   Branch는 `main` / 폴더는 `/docs`로 지정 후 저장
   - 최초 1회는 `docs/index.html`이 존재해야 폴더 선택지가 나타납니다. 로컬에서 `python -m src.main`을
     한 번 실행해 `docs/index.html`을 생성한 뒤 커밋/push하면 됩니다
   - 활성화 후 나오는 Pages URL(`https://<계정>.github.io/<저장소명>/`)이 상세 리포트 페이지 주소입니다
     (GitHub Actions에서는 `GITHUB_REPOSITORY` 값으로 이 URL을 자동으로 계산하므로 별도 등록이 필요 없습니다)
4. **Actions** 탭에서 `Daily Stock Report` 워크플로우 확인
   - 매일 06:00 KST(UTC 21:00) 자동 실행 — 데이터 수집 → `docs/index.html` 갱신 후 자동 커밋/push →
     카카오톡 요약 메시지 발송
   - `workflow_dispatch`로 수동 실행 테스트 가능

## 참고: refresh_token 만료

카카오 `refresh_token`은 발급 후 약 60일간 유효합니다. 액세스 토큰 갱신 시 카카오가 새 `refresh_token`을
함께 내려주는 경우, 실행 로그에 경고가 남습니다 — 이 경우 GitHub Secret의 `KAKAO_REFRESH_TOKEN` 값을
수동으로 갱신해야 합니다. 완전히 만료된 경우 `scripts/kakao_auth_setup.py`를 다시 실행해 재발급받으세요.
