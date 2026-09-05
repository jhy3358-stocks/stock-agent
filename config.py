"""추적 대상 종목 및 지수 정의."""

KR_STOCKS = {
    "005930": "삼성전자",
    "000660": "SK하이닉스",
    "005380": "현대차",
}

US_STOCKS = {
    "AAPL": "애플",
    "AMZN": "아마존닷컴",
    "AVGO": "브로드컴",
    "GOOGL": "알파벳 A",
    "META": "메타 플랫폼스",
    "MSFT": "마이크로소프트",
    "NVDA": "엔비디아",
    "TSLA": "테슬라",
    "MU": "마이크론",
    "SKHY": "SK하이닉스(나스닥)",
    "SPCX": "스페이스X",
}

# pykrx의 코스피 지수 조회 엔드포인트가 KRX 서버 세션 이슈로 불안정하여,
# 지수는 KOSPI 포함 전부 yfinance로 수집한다 (개별 국내 종목은 pykrx 그대로 사용).
INDICES = {
    "^GSPC": "S&P500",
    "^IXIC": "나스닥",
    "^KS11": "코스피",
}

MA_WINDOWS = (5, 20, 60)
RSI_PERIOD = 14

# 지표 계산에 필요한 최소 거래일 확보를 위해 넉넉히 조회
HISTORY_DAYS = 200

# DART corpCode.xml(수 MB)을 매일 다운로드/파싱하지 않도록, OpenDART API로 조회해
# 확인한 고유번호를 고정값으로 저장해둔다 (종목코드-corp_code 매핑은 사실상 불변).
KR_DART_CORP_CODES = {
    "005930": "00126380",  # 삼성전자
    "000660": "00164779",  # SK하이닉스
    "005380": "00164742",  # 현대차(현대자동차)
}

# 공시/뉴스 조회 기간 (일)
DISCLOSURE_LOOKBACK_DAYS = 2

# GRAV(Growth Risk-Adjusted Valuation) 모델 입력값.
# 적정주가 = 평균(Forward EPS) x 평균(Forward P/E) x (1 + g/100) / sqrt(beta)
#   Forward EPS/Forward P/E는 실행 시마다 Yahoo Finance(yfinance)와 Finviz에서
#   라이브로 조회해 평균낸다 (src/valuation.py 참고).
# g: 3~5년 이익성장률(%) 컨센서스, beta: 시장 대비 변동성 배수
# 이 두 값은 라이브로 안정적으로 구하기 어려워(특히 g) Yahoo Finance / Finviz
# (EPS next 5Y, Beta) / SimplyWall.st 등을 참고해 사람이 채워둔 값이다.
# 시간이 지나면 정확도가 떨어지므로 주기적으로 갱신해야 한다 (2026-08-28 기준 조사).
VALUATION = {
    # --- 국내 ---
    "005930": {"growth_rate": 36.5, "beta": 1.548},   # 삼성전자: g=SimplyWall.st 애널리스트 컨센서스, beta=Yahoo Finance
    "000660": {"growth_rate": 109.12, "beta": 2.395},  # SK하이닉스: g=Finviz(ADR SKHY, 동일기업), beta=Yahoo Finance
    "005380": {"growth_rate": 9.5, "beta": 1.723},    # 현대차: g=SimplyWall.st, beta=Yahoo Finance

    # --- 미국 ---
    "AAPL": {"growth_rate": 12.49, "beta": 1.086},
    "AMZN": {"growth_rate": 24.47, "beta": 1.454},
    "AVGO": {"growth_rate": 56.98, "beta": 1.473},
    "GOOGL": {"growth_rate": 18.16, "beta": 1.237},
    "META": {"growth_rate": 18.43, "beta": 1.243},
    "MSFT": {"growth_rate": 18.29, "beta": 1.099},
    "NVDA": {"growth_rate": 61.95, "beta": 2.215},
    "TSLA": {"growth_rate": 23.67, "beta": 1.827},
    "MU": {"growth_rate": 173.61, "beta": 2.213},
    "SKHY": {"growth_rate": 109.12, "beta": 2.395},
    # SPCX(스페이스X): 비상장 성격의 종목이라 Yahoo/Finviz/Seeking Alpha 어디에도
    # EPS 5년 성장률·베타가 공시되어 있지 않아 값을 채우지 않는다.
    # (밸류에이션 데이터 미확보 -> fair_value_line에 "적정주가 데이터 없음"으로 표시)
}

# 업종 피어그룹 평균 배수 (src.valuation의 relative_per_fair_value /
# relative_ev_ebitda_fair_value에서 사용). Finviz 개별 종목 페이지에서 동종업계
# 피어그룹(5~8개사)의 trailing PER / EV-EBITDA를 모아 평균낸 값이다
# (2026-09-06 기준 조사, 주기적 갱신 필요).
#   - 반도체(000660·AVGO·NVDA·MU): NVDA,AVGO,MU,INTC,QCOM,TXN,AMD,TSM
#   - 가전(005930·AAPL): AAPL,SONY
#   - 자동차(005380·TSLA): GM,F,TM (테슬라 자신의 극단적 배수는 업종 평균을
#     심하게 왜곡시켜 피어그룹에서 제외했다)
#   - 인터넷소매(AMZN): AMZN,BABA,JD,EBAY,ETSY
#   - 인터넷콘텐츠(GOOGL·META): GOOGL,META,PINS,BIDU
#   - 소프트웨어(MSFT): MSFT,ORCL,CRM,ADBE,NOW
# peer_ev_ebitda가 None인 항목은 원천 데이터가 깨져 있어(예: 000660은 yfinance
# EBITDA 필드 자체가 오염돼 있음이 확인됨) 의도적으로 비워둔 것이다.
RELATIVE_VALUATION = {
    "005930": {"peer_per": 29.30, "peer_ev_ebitda": 27.93},
    "000660": {"peer_per": 44.28, "peer_ev_ebitda": None},
    "005380": {"peer_per": 24.15, "peer_ev_ebitda": 14.50},
    "AAPL": {"peer_per": 29.30, "peer_ev_ebitda": 27.93},
    "AMZN": {"peer_per": 22.45, "peer_ev_ebitda": 13.64},
    "AVGO": {"peer_per": 44.28, "peer_ev_ebitda": 29.33},
    "GOOGL": {"peer_per": 33.41, "peer_ev_ebitda": 24.69},
    "META": {"peer_per": 33.41, "peer_ev_ebitda": 24.69},
    "MSFT": {"peer_per": 36.48, "peer_ev_ebitda": 24.14},
    "NVDA": {"peer_per": 44.28, "peer_ev_ebitda": 29.33},
    "TSLA": {"peer_per": 24.15, "peer_ev_ebitda": 14.50},
    "MU": {"peer_per": 44.28, "peer_ev_ebitda": 29.33},
}
