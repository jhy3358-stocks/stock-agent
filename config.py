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
    "RKLB": "로켓랩",
    "MRVL": "마벨 테크놀로지",
    "LITE": "루멘텀",
    "COHR": "코히런트",
    "LLY": "일라이릴리",
    "ANET": "아리스타 네트웍스",
    "SNDK": "샌디스크",
    "COST": "코스트코",
    "CRDO": "크레도 테크놀로지",
    "ALAB": "아스테라랩스",
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

# 주요 지수 카드에 붙일 뉴스 검색 키.
#   - 미국 지수: Yahoo Finance 지수 티커 뉴스 (Seeking Alpha RSS는 지수 티커를
#     지원하지 않아 0건이고, ETF(SPY/QQQ) 피드는 ETF 상품 기사 위주라 쓰지 않는다)
#   - 국내 지수: 네이버 뉴스 검색어. "코스피"/"코스닥" 단독 검색은 두 지수 결과가
#     같은 시황 기사로 거의 겹쳐서 "지수"를 붙여 구분한다.
US_INDEX_NEWS_TICKERS = ("^GSPC", "^IXIC")
KR_INDEX_NEWS_QUERIES = {
    "^KS11": "코스피 지수",
    "^KQ11": "코스닥 지수",
}

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
    # (VALUATION 미확보 -> GRAV/M-GRAV 대신 Growth FV 모듈로 라우팅됨. src/growth_data.py 참고)
    "MRVL": {"growth_rate": 53.85, "beta": 2.28},  # Finviz(EPS next 5Y/Beta), 2026-09-25 기준 조사
    "LITE": {"growth_rate": 76.28, "beta": 1.54},  # Finviz(EPS next 5Y/Beta), 2026-09-25 기준 조사
    "COHR": {"growth_rate": 48.98, "beta": 2.11},  # Finviz(EPS next 5Y/Beta), 2026-09-25 기준 조사
    "LLY": {"growth_rate": 30.55, "beta": 0.45},   # Finviz(EPS next 5Y/Beta), 2026-09-25 기준 조사
    "ANET": {"growth_rate": 28.98, "beta": 1.61},  # Finviz(EPS next 5Y/Beta), 2026-09-25 기준 조사
    # SNDK(샌디스크): 2025년 WDC에서 스핀오프된 지 얼마 안 돼 beta가 아직 불안정할
    # 수 있다(Finviz 5.20 - 다른 종목 대비 이례적으로 높음). 주기적으로 재확인 필요.
    "SNDK": {"growth_rate": 54.54, "beta": 5.20},  # Finviz(EPS next 5Y/Beta), 2026-09-25 기준 조사
    "COST": {"growth_rate": 11.03, "beta": 0.88},  # Finviz(EPS next 5Y/Beta), 2026-09-25 기준 조사
    "CRDO": {"growth_rate": 52.78, "beta": 3.24},  # Finviz(EPS next 5Y/Beta), 2026-09-25 기준 조사
    "ALAB": {"growth_rate": 64.96, "beta": 3.73},  # Finviz(EPS next 5Y/Beta), 2026-09-25 기준 조사
    # RKLB(로켓랩): forward EPS가 소스마다 부호가 엇갈리고(Yahoo +0.046 vs
    # Finviz 내년 EPS -0.04) EPS next 5Y 자체가 없어(적자 기업) GRAV에 넣지
    # 않는다. TTM EBITDA 마진이 아직 음수라 Growth FV 2단계로 라우팅됨
    # (config/growth_assumptions.yaml 참고).
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
#     종목에 한해 None 처리 - 2026-09 기준 005930/000660/TSLA).
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
    "TSLA": {"target_pe": None, "m_score": 48},    # FSD/배터리 기술력은 있으나 EV 경쟁 심화로 락인·이익률 약화 중. target_pe는 라이브 forward PE 사용
    "MU": {"target_pe": 12.0, "m_score": 49},      # 메모리 3강 중 기술격차 상대적으로 작아 SK하이닉스보다 해자 약함
    "SKHY": {"target_pe": 12.0, "m_score": 67},    # SK하이닉스(ADR), 000660과 동일 기업

    # --- 2026-09-25 추가 (m_score는 2026-09-25 시점 사업 구조 기준 최초 산정) ---
    "MRVL": {"target_pe": 30.0, "m_score": 66},    # AI 커스텀실리콘(AWS/구글向) 설계선점 + 광인터커넥트, OPM은 AVGO/NVDA 대비 한 단계 아래
    "LITE": {"target_pe": 22.0, "m_score": 53},    # 광부품(데이터센터 광트랜시버) 기술력은 있으나 경쟁 심하고 수익성 변동성 큰 부품업체
    "COHR": {"target_pe": 20.0, "m_score": 57},    # 소재~모듈 수직계열화된 포토닉스 업체(II-VI+Coherent 합병), 다각화로 락인은 중간
    "LLY": {"target_pe": 30.0, "m_score": 82},     # GLP-1(마운자로/젭바운드) 특허 독점 프랜차이즈, 압도적 마진(EBITDA 52%)·진입장벽. beta<1이라 M-GRAV 공식상 GRAV보다 더 부풀 수 있음(아래 요약 참고)
    "ANET": {"target_pe": 35.0, "m_score": 73},    # AI/클라우드 데이터센터 스위칭 선두, EOS 소프트웨어로 배포 후 전환비용 큼, OPM 최상위권
    "SNDK": {"target_pe": None, "m_score": 41},    # NAND는 사실상 범용재라 기술/락인 해자 약하고 사이클 마진(현재 EBITDA 62%는 업사이클 고점). target_pe는 라이브 forward PE 사용
    "COST": {"target_pe": 35.0, "m_score": 52},    # 멤버십 갱신율(~90%+)에서 오는 행동적 락인은 최상위권이나 마진 자체는 유통업 특성상 얇음(EBITDA 5%)
    "CRDO": {"target_pe": 18.0, "m_score": 58},    # AI 인터커넥트용 SerDes/AEC 설계선점, OPM은 양호하나 소형주라 대형 경쟁사(AVGO/MRVL) 대비 해자 얕음
    "ALAB": {"target_pe": 45.0, "m_score": 61},    # PCIe/CXL 리타이머로 Nvidia AI 서버 생태계에 초기 선점, 아직 스케일업 중이라 OPM 체력은 진행형
    # SPCX/RKLB: VALUATION에 g/beta가 없어 M-GRAV도 계산 불가 (Growth FV 모듈로 대체, src/growth_data.py 참고).
}
