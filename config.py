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
}

# pykrx의 코스피 지수 조회 엔드포인트가 KRX 서버 세션 이슈로 불안정하여,
# 지수는 KOSPI 포함 전부 yfinance로 수집한다 (개별 국내 종목은 pykrx 그대로 사용).
INDICES = {
    "^KS11": "코스피",
    "^IXIC": "나스닥",
    "^GSPC": "S&P500",
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
