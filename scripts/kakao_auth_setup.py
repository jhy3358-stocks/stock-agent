"""카카오톡 '나에게 보내기' 최초 인증 스크립트 (1회 실행).

사용법:
    1. .env 파일에 KAKAO_REST_API_KEY, KAKAO_REDIRECT_URI를 채워둔다.
       (KAKAO_REDIRECT_URI는 https://developers.kakao.com/tool/oauth 사용을 권장)
    2. python scripts/kakao_auth_setup.py 실행
    3. 출력된 인가 URL을 브라우저로 열어 카카오 로그인/동의
    4. 리다이렉트된 페이지 URL의 `code=` 파라미터 값을 터미널에 붙여넣기
    5. refresh_token이 .kakao_token.json에 저장되고, GitHub Secrets 등록 안내가 출력됨
"""
from __future__ import annotations

import json
import os
import sys
import urllib.parse
from pathlib import Path

import requests
from dotenv import load_dotenv

KAUTH_AUTHORIZE_URL = "https://kauth.kakao.com/oauth/authorize"
KAUTH_TOKEN_URL = "https://kauth.kakao.com/oauth/token"
TOKEN_FILE = Path(__file__).resolve().parent.parent / ".kakao_token.json"


def main() -> None:
    load_dotenv()
    rest_api_key = os.environ.get("KAKAO_REST_API_KEY")
    redirect_uri = os.environ.get(
        "KAKAO_REDIRECT_URI", "https://developers.kakao.com/tool/oauth"
    )

    if not rest_api_key:
        print("오류: .env 파일에 KAKAO_REST_API_KEY를 먼저 설정하세요.")
        sys.exit(1)

    params = {
        "client_id": rest_api_key,
        "redirect_uri": redirect_uri,
        "response_type": "code",
        "scope": "talk_message",
    }
    authorize_url = f"{KAUTH_AUTHORIZE_URL}?{urllib.parse.urlencode(params)}"

    print("아래 URL을 브라우저에서 열어 카카오 로그인 및 동의를 진행하세요:\n")
    print(authorize_url)
    print(
        "\n동의 후 리다이렉트된 페이지의 URL에서 'code=' 뒤의 값을 복사해 아래에 붙여넣으세요."
    )
    code = input("인가 코드(code): ").strip()

    token_response = requests.post(
        KAUTH_TOKEN_URL,
        data={
            "grant_type": "authorization_code",
            "client_id": rest_api_key,
            "redirect_uri": redirect_uri,
            "code": code,
        },
        timeout=10,
    )
    if token_response.status_code != 200:
        print(f"토큰 발급 실패 (status={token_response.status_code}): {token_response.text}")
        sys.exit(1)

    payload = token_response.json()
    refresh_token = payload["refresh_token"]

    TOKEN_FILE.write_text(
        json.dumps({"refresh_token": refresh_token}, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )

    print(f"\nrefresh_token이 {TOKEN_FILE}에 저장되었습니다.")
    print("\n다음 두 값을 GitHub 저장소 Settings > Secrets and variables > Actions에 등록하세요:")
    print(f"  KAKAO_REST_API_KEY = {rest_api_key}")
    print(f"  KAKAO_REFRESH_TOKEN = {refresh_token}")
    print(
        "\n(참고) 카카오 refresh_token은 발급 후 약 60일간 유효하며, "
        "만료 시 이 스크립트를 다시 실행해 재발급받아야 합니다."
    )


if __name__ == "__main__":
    main()
