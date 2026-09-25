"""전체 파이프라인: 데이터 수집 -> 지표 계산 -> 리포트 생성 -> 카카오톡 발송."""
from __future__ import annotations

import logging
import os
from pathlib import Path
from typing import Optional

from dotenv import load_dotenv

from config import (
    DISCLOSURE_LOOKBACK_DAYS,
    INDICES,
    KR_DART_CORP_CODES,
    KR_INDEX_NEWS_QUERIES,
    KR_STOCKS,
    NEWS_LOOKBACK_HOURS,
    US_INDEX_NEWS_TICKERS,
    US_STOCKS,
)
from src.dart_client import get_recent_disclosures_for_stocks
from src.html_report import build_html_report
from src.kakao_client import send_summary
from src.kr_stocks import fetch_all_kr_stocks
from src.naver_news_client import get_recent_news_for_stocks as get_naver_news_for_stocks
from src.news_client import (
    dedupe_news_across,
    get_recent_news_for_tickers,
    get_recent_yahoo_news_for_tickers,
)
from src.report import build_kakao_summary, build_report_sections
from src.sec_client import get_recent_filings_for_tickers
from src.us_stocks import fetch_all_us_stocks, fetch_indices

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger(__name__)

DOCS_DIR = Path(__file__).resolve().parent.parent / "docs"

# 주요 지수 카드당 뉴스 개수와, 지수 간 중복 제거 전에 받아둘 후보 수
INDEX_NEWS_LIMIT = 2
INDEX_NEWS_POOL_SIZE = 10


def _resolve_report_page_url() -> str:
    """REPORT_PAGE_URL이 설정되어 있으면 그 값을, GitHub Actions 환경이면
    GITHUB_REPOSITORY로부터 Pages URL을 자동 유추한다."""
    explicit = os.environ.get("REPORT_PAGE_URL")
    if explicit:
        return explicit

    repository = os.environ.get("GITHUB_REPOSITORY")  # "owner/repo"
    if repository and "/" in repository:
        owner, repo = repository.split("/", 1)
        return f"https://{owner}.github.io/{repo}/"

    logger.warning(
        "REPORT_PAGE_URL이 설정되지 않아 임시 링크(https://github.com)를 사용합니다. "
        "GitHub Pages 설정 후 REPORT_PAGE_URL을 등록하세요."
    )
    return "https://github.com"


def _collect_index_news(naver_credentials: Optional[tuple[str, str]]) -> dict:
    """주요 지수 카드 뉴스. 미국 지수는 Yahoo, 국내 지수는 네이버(인증키가 있을 때).

    지수끼리 같은 시황 기사가 겹치는 일이 잦아, 후보를 넉넉히 받아둔 뒤 INDICES
    순서대로 중복을 걸러 지수별 INDEX_NEWS_LIMIT개씩 채운다.
    """
    logger.info("주요 지수 뉴스 조회 중...")
    pool = get_recent_yahoo_news_for_tickers(
        list(US_INDEX_NEWS_TICKERS), limit=INDEX_NEWS_POOL_SIZE, hours=NEWS_LOOKBACK_HOURS
    )
    if naver_credentials:
        pool.update(
            get_naver_news_for_stocks(
                *naver_credentials,
                KR_INDEX_NEWS_QUERIES,
                limit=INDEX_NEWS_POOL_SIZE,
                hours=NEWS_LOOKBACK_HOURS,
                # 지수명만으로 검색하면 본문에 한 번 언급된 연예 기사 등이 섞여,
                # 제목에 지수명이 들어간 기사만 남긴다.
                require_query_in_title=True,
            )
        )
    return dedupe_news_across(pool, list(INDICES.keys()), INDEX_NEWS_LIMIT)


def main() -> None:
    load_dotenv()

    logger.info("국내 종목 데이터 수집 중...")
    kr_stocks = fetch_all_kr_stocks()

    logger.info("미국 종목 및 지수 데이터 수집 중...")
    us_stocks = fetch_all_us_stocks()
    indices = fetch_indices()

    for section in build_report_sections(kr_stocks, us_stocks, indices):
        print(section)
        print("\n" + "=" * 40 + "\n")

    logger.info("SEC 공시 조회 중...")
    us_filings = get_recent_filings_for_tickers(
        list(US_STOCKS.keys()), DISCLOSURE_LOOKBACK_DAYS
    )

    logger.info("Yahoo Finance / Seeking Alpha 뉴스 조회 중...")
    us_news = get_recent_news_for_tickers(
        list(US_STOCKS.keys()), hours=NEWS_LOOKBACK_HOURS
    )

    dart_api_key = os.environ.get("DART_API_KEY")
    if dart_api_key:
        logger.info("DART 공시 조회 중...")
        kr_disclosures = get_recent_disclosures_for_stocks(
            dart_api_key, KR_DART_CORP_CODES, DISCLOSURE_LOOKBACK_DAYS
        )
    else:
        logger.warning("DART_API_KEY가 설정되지 않아 국내 공시 조회를 건너뜁니다.")
        kr_disclosures = {}

    naver_client_id = os.environ.get("NAVER_CLIENT_ID")
    naver_client_secret = os.environ.get("NAVER_CLIENT_SECRET")
    naver_credentials = (
        (naver_client_id, naver_client_secret) if naver_client_id and naver_client_secret else None
    )
    if naver_credentials:
        logger.info("네이버 뉴스 조회 중...")
        kr_news = get_naver_news_for_stocks(*naver_credentials, KR_STOCKS, hours=NEWS_LOOKBACK_HOURS)
    else:
        logger.warning(
            "NAVER_CLIENT_ID/NAVER_CLIENT_SECRET이 설정되지 않아 국내 뉴스·국내 지수 뉴스 조회를 건너뜁니다."
        )
        kr_news = {}

    index_news = _collect_index_news(naver_credentials)

    DOCS_DIR.mkdir(exist_ok=True)
    (DOCS_DIR / "index.html").write_text(
        build_html_report(
            kr_stocks, us_stocks, indices, kr_disclosures, us_filings, us_news, kr_news,
            index_news,
        ),
        encoding="utf-8",
    )
    logger.info("HTML 리포트 생성 완료: %s", DOCS_DIR / "index.html")

    rest_api_key = os.environ.get("KAKAO_REST_API_KEY")
    refresh_token = os.environ.get("KAKAO_REFRESH_TOKEN")

    if not rest_api_key or not refresh_token:
        logger.warning(
            "KAKAO_REST_API_KEY 또는 KAKAO_REFRESH_TOKEN이 설정되지 않아 "
            "카카오톡 발송을 건너뜁니다 (리포트 콘솔 출력만 수행)."
        )
        return

    page_url = _resolve_report_page_url()
    summary = build_kakao_summary(kr_stocks, us_stocks, indices, page_url)
    logger.info("카카오톡 발송 중...")
    token_payload = send_summary(rest_api_key, refresh_token, summary, page_url)
    logger.info("발송 완료")

    new_refresh_token = token_payload.get("refresh_token")
    if new_refresh_token and new_refresh_token != refresh_token:
        logger.warning(
            "카카오가 새 refresh_token을 발급했습니다 "
            "(워크플로가 KAKAO_REFRESH_TOKEN 시크릿을 자동 갱신)."
        )
        token_file = os.environ.get("KAKAO_NEW_TOKEN_FILE")
        if token_file:
            Path(token_file).write_text(new_refresh_token, encoding="utf-8")
            logger.info("새 refresh_token을 %s에 기록했습니다.", token_file)


if __name__ == "__main__":
    main()
