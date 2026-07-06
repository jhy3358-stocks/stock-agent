"""전체 파이프라인: 데이터 수집 -> 지표 계산 -> 리포트 생성 -> 카카오톡 발송."""
from __future__ import annotations

import logging
import os
from pathlib import Path

from dotenv import load_dotenv

from config import DISCLOSURE_LOOKBACK_DAYS, KR_DART_CORP_CODES, US_STOCKS
from src.dart_client import get_recent_disclosures_for_stocks
from src.html_report import build_html_report
from src.kakao_client import send_summary
from src.kr_stocks import fetch_all_kr_stocks
from src.news_client import get_recent_news_for_tickers
from src.report import build_kakao_summary, build_report_sections
from src.sec_client import get_recent_filings_for_tickers
from src.us_stocks import fetch_all_us_stocks, fetch_indices

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger(__name__)

DOCS_DIR = Path(__file__).resolve().parent.parent / "docs"


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
        list(US_STOCKS.keys()), days=DISCLOSURE_LOOKBACK_DAYS
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

    DOCS_DIR.mkdir(exist_ok=True)
    (DOCS_DIR / "index.html").write_text(
        build_html_report(
            kr_stocks, us_stocks, indices, kr_disclosures, us_filings, us_news
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
    send_summary(rest_api_key, refresh_token, summary, page_url)
    logger.info("발송 완료")


if __name__ == "__main__":
    main()
