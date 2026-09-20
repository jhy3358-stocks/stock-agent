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
    "^KQ11": "코스닥",
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

# 공시(SEC/DART) 조회 기간 (일)
DISCLOSURE_LOOKBACK_DAYS = 2

# 뉴스는 날짜를 화면에 표시하지 않으므로, 며칠 전 기사인지 헷갈리지 않도록
# "최근 몇 시간"으로 판단한다 (달력상 날짜로 자르면 실행 시간대에 따라
# 관련 뉴스가 통째로 비어버릴 수 있어 24시간 롤링 윈도를 사용).
NEWS_LOOKBACK_HOURS = 24

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

# EV-EBITDA 상대가치가 쓰는 순부채(=이자부 차입금 - 현금성자산).
# yfinance info["totalDebt"]는 리스부채(운용리스 포함)까지 합산해 순부채를
# 크게 부풀리는 경우가 확인됐다(AMZN: yfinance 기준 순부채 ~$128.6B vs 실제
# 10-Q 기준 ~$9.6B, 약 13배 과대). 그래서 리스부채를 뺀 순수 이자부 차입금
# (단기차입금+유동성장기부채+사채+장기차입금 등)만 원문 재무제표에서 직접
# 가져와 고정값으로 쓴다. 분기가 지나면 갱신 필요.
#   - 국내 3종목: DART 반기보고서(2026-06-30, 연결기준 CFS)
#   - 미국 9종목: SEC EDGAR XBRL companyfacts(가장 최근 10-Q, MSFT는 회계연도가
#     6월 말이라 10-K)의 LongTermDebt(Noncurrent+Current)+ShortTermBorrowings류
#     합계 - (CashAndCashEquivalents + 유동 MarketableSecurities/단기투자)
# 단위: 원화 종목은 KRW, 미국 종목은 USD (원 단위, 백만/천 단위 아님)
NET_DEBT = {
    "005930": {"debt": 22_408_721_000_000, "cash": 189_953_028_000_000},  # 2026-06-30 DART 반기보고서
    "000660": {"debt": 18_586_634_000_000, "cash": 87_957_923_000_000},  # 2026-06-30 DART 반기보고서
    # SKHY(SK하이닉스 나스닥 ADR)는 본사와 동일 기업 - 000660과 같은 KRW 값.
    # RELATIVE_VALUATION에 SKHY 항목이 없어 현재는 실사용되지 않는다.
    "SKHY": {"debt": 18_586_634_000_000, "cash": 87_957_923_000_000},  # 2026-06-30 DART 반기보고서(000660과 동일)
    "005380": {"debt": 188_805_180_000_000, "cash": 25_994_018_000_000},  # 2026-06-30 DART 반기보고서(현대캐피탈 등 금융자회사 여신부채 포함)
    "AAPL": {"debt": 84_344_000_000, "cash": 62_399_000_000},  # 2026-06-27 10-Q
    "AMZN": {"debt": 132_549_000_000, "cash": 122_988_000_000},  # 2026-06-30 10-Q
    "AVGO": {"debt": 59_419_000_000, "cash": 23_975_000_000},  # 2026-08-02 10-Q
    "GOOGL": {"debt": 100_164_000_000, "cash": 242_474_000_000},  # 2026-06-30 10-Q
    "META": {"debt": 83_664_000_000, "cash": 90_260_000_000},  # 2026-06-30 10-Q
    "MSFT": {"debt": 40_294_000_000, "cash": 76_843_000_000},  # 2026-06-30 10-K(FY26)
    "NVDA": {"debt": 33_366_000_000, "cash": 56_586_000_000},  # 2026-07-26 10-Q
    "TSLA": {"debt": 9_061_000_000, "cash": 43_524_000_000},  # 2026-06-30 10-Q
    "MU": {"debt": 5_722_000_000, "cash": 24_995_000_000},  # 2026-05-28 10-Q
}

# M-GRAV(해자 반영 GRAV) 모델 입력값 - DCF를 대체하는 종합모델 후보 (m-grave.jpeg 산식).
#   적정주가 = Forward EPS x Target P/E x (1 + g/100) / beta^(1/m_factor)
#   Forward EPS는 기존 GRAV와 동일하게 실행 시 Yahoo/Finviz 라이브 평균을 쓰고,
#   g(성장률)·beta는 위 VALUATION 값을 그대로 재사용한다.
#   target_pe: 향후 3~5년 평균으로 봤을 때 "적정"하다고 판단하는 타겟 P/E
#     멀티플. 라이브 forward PE(현재 시장가 기준)와 달리 업종 특성·이익
#     듀레이션을 감안해 사람이 채워둔 값이다. None이면 원칙대로 GRAV와 동일한
#     라이브 forward PE(Yahoo/Finviz 평균)를 그대로 target_pe로 쓴다
#     (커스텀 타겟 멀티플 추정치가 라이브 값과 크게 어긋나 신뢰하기 어려운
#     종목에 한해 None 처리 - 2026-09 기준 005930/000660).
#   m_score: 0~100점, 아래 4개 항목을 각 25점 배점으로 정성 평가해 합산한다.
#     1) 기술독점성 & 시장점유율   2) 전환비용 & 생태계 락인(lock-in)
#     3) 영업이익률(OPM) 체력     4) 원가/자본/특허 등 진입장벽
#   m_factor = 1 + m_score/100 (0.0~1.0 -> 1.0~2.0), beta의 지수를 1/m_factor로
#     눌러줘 해자가 강할수록(m_score 높을수록) 베타(변동성) 페널티를 완화한다.
#   정성적 판단 비중이 커서 g/beta보다도 더 자주 재검토가 필요하다
#   (2026-09 기준 최초 산정).
M_GRAV = {
    # --- 국내 ---
    "005930": {"target_pe": None, "m_score": 55},  # 삼성전자: 메모리+파운드리+세트 다각화, 부문별 이익률 편차 커 체력/락인 보통. target_pe는 라이브 forward PE 사용
    "000660": {"target_pe": None, "m_score": 67},  # SK하이닉스: HBM 기술 선두, 공급 qualification 장벽, 사이클 고점 OPM 우수. target_pe는 라이브 forward PE 사용
    "005380": {"target_pe": 6.0, "m_score": 36},   # 현대차: 자본집약 완성차, 브랜드 전환비용 낮고 이익률 얇음
    # --- 미국 ---
    "AAPL": {"target_pe": 27.0, "m_score": 76},    # iOS/서비스 생태계 락인, 하드웨어 마진은 준수하나 최상위는 아님
    "AMZN": {"target_pe": 32.0, "m_score": 64},    # AWS 락인/규모의 경제 강하지만 커머스 부문 이익률이 전체를 희석
    "AVGO": {"target_pe": 28.0, "m_score": 77},    # 통신칩 IP독점 + VMware 인수로 소프트웨어 락인 추가, OPM 최상위권
    "GOOGL": {"target_pe": 22.0, "m_score": 71},   # 검색 독점적 지위, 광고주 전환비용은 낮은 편
    "META": {"target_pe": 23.0, "m_score": 69},    # SNS 네트워크효과 강하나 광고 플랫폼 자체 전환장벽은 중간
    "MSFT": {"target_pe": 30.0, "m_score": 83},    # Office/Windows/Azure 전방위 엔터프라이즈 락인, OPM 최상위권
    "NVDA": {"target_pe": 35.0, "m_score": 93},    # CUDA 생태계 독점적 락인 + AI GPU 시장점유율, 진입장벽/OPM 모두 최상위
    "TSLA": {"target_pe": 55.0, "m_score": 48},    # FSD/배터리 기술력은 있으나 EV 경쟁 심화로 락인·이익률 약화 중
    "MU": {"target_pe": 12.0, "m_score": 49},      # 메모리 3강 중 기술격차 상대적으로 작아 SK하이닉스보다 해자 약함
    "SKHY": {"target_pe": 12.0, "m_score": 67},    # SK하이닉스(ADR), 000660과 동일 기업
    # SPCX: VALUATION에 g/beta가 없어 M-GRAV도 계산 불가(적정주가 데이터 없음).
}
