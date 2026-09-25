"""카카오톡 '나에게 보내기' 발송 클라이언트.

REST API를 직접 호출한다 (requests 기반, 외부 카카오 전용 라이브러리 미사용).
매 실행마다 저장된 refresh_token으로 access_token을 새로 발급받아 사용한다.
"""
from __future__ import annotations

import json

import requests

KAUTH_TOKEN_URL = "https://kauth.kakao.com/oauth/token"
KAPI_MEMO_SEND_URL = "https://kapi.kakao.com/v2/api/talk/memo/default/send"


class KakaoAuthError(RuntimeError):
    pass


class KakaoSendError(RuntimeError):
    pass


def _request_token(data: dict, failure: str) -> dict:
    response = requests.post(KAUTH_TOKEN_URL, data=data, timeout=10)
    if response.status_code != 200:
        raise KakaoAuthError(f"{failure} (status={response.status_code}): {response.text}")
    return response.json()


def exchange_auth_code(rest_api_key: str, redirect_uri: str, code: str) -> dict:
    """최초 인증 시 인가 코드로 access/refresh token을 발급받는다 (scripts/kakao_auth_setup.py)."""
    return _request_token(
        {
            "grant_type": "authorization_code",
            "client_id": rest_api_key,
            "redirect_uri": redirect_uri,
            "code": code,
        },
        "토큰 발급 실패",
    )


def refresh_access_token(rest_api_key: str, refresh_token: str) -> dict:
    """refresh_token으로 새 access_token을 발급받는다.

    반환값에 'refresh_token'이 포함되어 있으면 카카오 측에서 토큰을 회전한 것이므로,
    호출부(src/main.py)에서 이를 감지해 저장된 값을 갱신해야 한다.
    """
    return _request_token(
        {
            "grant_type": "refresh_token",
            "client_id": rest_api_key,
            "refresh_token": refresh_token,
        },
        "access_token 갱신 실패",
    )


def send_text_to_me(
    access_token: str, text: str, link_url: str, button_title: str = "상세 리포트 보기"
) -> None:
    """카카오톡 '나에게 보내기'로 텍스트 메시지 1건을 발송한다.

    button_title을 지정해야 메시지에 클릭 가능한 버튼(링크)이 표시된다.
    """
    template_object = {
        "object_type": "text",
        "text": text,
        "link": {
            "web_url": link_url,
            "mobile_web_url": link_url,
        },
        "button_title": button_title,
    }
    response = requests.post(
        KAPI_MEMO_SEND_URL,
        headers={"Authorization": f"Bearer {access_token}"},
        data={"template_object": json.dumps(template_object, ensure_ascii=False)},
        timeout=10,
    )
    if response.status_code != 200:
        raise KakaoSendError(
            f"카카오톡 발송 실패 (status={response.status_code}): {response.text}"
        )


def send_summary(rest_api_key: str, refresh_token: str, text: str, link_url: str) -> dict:
    """요약 텍스트 메시지 1건을 상세 리포트 링크와 함께 발송한다.

    반환값은 refresh_access_token()의 원본 페이로드로, 카카오가 refresh_token을
    새로 발급했는지(로테이션) 호출부에서 확인할 때 사용한다.
    """
    token_payload = refresh_access_token(rest_api_key, refresh_token)
    send_text_to_me(token_payload["access_token"], text, link_url)
    return token_payload

