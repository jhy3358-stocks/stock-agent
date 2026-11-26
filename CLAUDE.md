# Daily Stock Report

국내·미국 주요 지수, 투자지표, 개별 종목을 모아 HTML 리포트(`docs/index.html`, GitHub Pages)를
만들고 카카오톡 '나에게 보내기'로 요약을 발송한다. 진입점은 `python -m src.main`.

## 공통

- 실행: GitHub Actions `workflow_dispatch`(`.github/workflows/daily_report.yml`)를 외부 스케줄러
  (cron-job.org)가 호출한다. 리포트 시각은 한국 시간 08:00 / 17:00 / 21:30. 발송 구간은
  월 06:00 ~ 토 06:59 KST(`src/main.py` `in_send_window`), 밖에서는 `REPORT_FORCE=true`일 때만.
- CI는 Python 3.11, 로컬 `.venv`는 3.9 — 3.10+ 전용 문법(`match`, `X | Y` 런타임 타입 등)과
  3.9의 `fromisoformat` 한계(`-0500` 오프셋 미지원)에 주의.
- 테스트: `.venv/bin/python -m pytest -q tests/` (네트워크 없이 monkeypatch로 고정).
- 외부 조회는 항목별로 실패를 격리한다: `src/concurrency.py`의 `fetch_all` / `safe_call`로
  감싸 실패 시 경고 로그 + 기본값. 조회 하나 때문에 리포트·발송이 멈추면 안 된다.
- yfinance는 `src/yf_data.py`의 `price_history`(종가 NaN 행 제거, sqlite 잠금 재시도)를 쓴다.
- 워크플로가 커밋하는 캐시: `data/consensus_cache.json`(예상치), `data/dart_cache.json`(DART).
- 모듈 docstring에 데이터 출처·예외 사례(날짜 포함)를 적어 두는 관례를 따른다.
- 표시 관련 공통 헬퍼는 `src/formatting.py`, HTML은 `src/html_report.py`, 텍스트·카카오 요약은
  `src/report.py`.

## 주요 지수

- 정의: `config.INDICES`(S&P500 `^GSPC`, 나스닥 `^IXIC`, 코스피 `^KS11`, 코스닥 `^KQ11`).
  pykrx 코스피 지수 조회가 불안정해 지수는 전부 yfinance(`src/us_stocks.py` `fetch_indices`).
- 장 마감 후(`src/extended_hours.py`): 미국 지수는 지수 선물(`config.INDEX_FUTURES` ES=F·NQ=F)의
  정규장 마감 시점 대비 등락률만(선물 가격 수준은 쓰지 않음), 미국 종목은 시간외 5분봉
  (prepost) 마지막 값. 정규장 중엔 표시 안 함. 국내 지수는 무료 야간 시세가 없어 제외.
- 지수 카드 뉴스: 미국은 Yahoo 지수 티커 뉴스(`config.US_INDEX_NEWS_TICKERS`), 국내는 네이버
  뉴스 검색(`config.KR_INDEX_NEWS_QUERIES`, 제목에 지수명 포함 기사만). 지수 간 중복 기사 제거
  (`src/main.py` `_collect_index_news`).

## 투자지표 (`src/macro_indicators.py`)

- 물가 CPI·PPI·PCE: FRED CSV. 전월비는 SA, 전년비는 NSA(PCE는 SA만 있어 둘 다 SA).
  속보치는 ALFRED vintage(`FIRST_RELEASE_VINTAGE`), 수정치는 현재 FRED 값.
- 예상치: ForexFactory 이번 주 일정(`FF_EVENTS`)을 `data/consensus_cache.json`에 누적.
  발표월의 전달을 대상월로 본다.
- 노출 규칙(`release_phase`): 물가는 발표 주 월요일(KST)부터 예상치, 발표일·다음 날 발표치.
  실업수당(ICSA)은 발표일만 예상치. 발표치 옆에 예상치 대비 상회/하회/부합(표시 자릿수 기준).
- 국채 2/10/30년: CNBC 실시간 우선, 실패 시 재무부 CSV. 등락은 last와 전일 종가로 직접 계산
  (CNBC change_pct 부호 오류 사례 있음).
- 달러 인덱스·유가·광물: yfinance 5분봉 마지막 값 + 일봉 전일 종가(근월물 선물).

## 개별 종목 — 미국

- 목록: `config.US_STOCKS`. 시세 `src/us_stocks.py`, 공시 SEC EDGAR(`src/sec_client.py`),
  뉴스 Yahoo·Seeking Alpha·Bloomberg(구글 뉴스 RSS, `config.BLOOMBERG_NEWS_NAMES`).
- 적정주가(`src/valuation.py`, `src/signal.py`): GRAV → M-GRAV / M-GRAV(FCI) → Growth FV
  (`src/growth_valuation.py`) → 최후 폴백 RSI50 평균가(`src/rsi50.py`).
  EPS는 영업이익 기반 연 환산(`src/sec_operating_eps.py`), 베타는 2년 주간 + 블룸 보정
  (`src/beta.py`), 기관 목표주가는 기관 기준 중복 제거 평균(`src/analyst_targets.py`).
- 신규상장 첫날은 상장가(`LISTING_PRICES`) 대비 등락.

## 개별 종목 — 한국

- 목록: `config.KR_STOCKS`. 시세 pykrx(`src/kr_stocks.py`), 공시·EPS는 OpenDART
  (`config.KR_DART_CORP_CODES` 고정 매핑, 실패 시 `src/dart_cache.py`), 뉴스는 네이버 검색 API.
- Target P/E는 네이버페이 증권 컨센서스(`src/naver_finance_client.py`)에
  코리아 디스카운트(`config.KOREA_DISCOUNT`) 적용. 베타 기준 지수는 코스피.

## 작업 원칙

- 적정주가·지표 공식은 요청한 대로만 바꾸고, 해석이 갈리면 먼저 묻는다.
- 시크릿(`.env`, `.kakao_token.json`)과 참고용 파일(`ndx_m_score.csv`, `m_score_by_stock.*`)은
  커밋하지 않는다.
