"""카카오톡 '나에게 보내기' 발송 클라이언트.

REST API를 직접 호출한다 (requests 기반, 외부 카카오 전용 라이브러리 미사용).
매 실행마다 저장된 refresh_token으로 access_token을 새로 발급받아 사용한다.
"""
from __future__ import annotations

import logging

import requests

KAUTH_TOKEN_URL = "https://kauth.kakao.com/oauth/token"
KAPI_MEMO_SEND_URL = "https://kapi.kakao.com/v2/api/talk/memo/default/send"

logger = logging.getLogger(__name__)


class KakaoAuthError(RuntimeError):
    pass


class KakaoSendError(RuntimeError):
    pass


def refresh_access_token(rest_api_key: str, refresh_token: str) -> dict:
    """refresh_token으로 새 access_token을 발급받는다.

    반환값에 'refresh_token'이 포함되어 있으면 카카오 측에서 토큰을 회전한 것이므로,
    호출부에서 이를 감지해 저장된 값을 갱신해야 한다.
    """
    response = requests.post(
        KAUTH_TOKEN_URL,
        data={
            "grant_type": "refresh_token",
            "client_id": rest_api_key,
            "refresh_token": refresh_token,
        },
        timeout=10,
    )
    if response.status_code != 200:
        raise KakaoAuthError(
            f"access_token 갱신 실패 (status={response.status_code}): {response.text}"
        )
    payload = response.json()
    if "refresh_token" in payload:
        logger.warning(
            "카카오가 새 refresh_token을 발급했습니다. "
            "GitHub Secrets의 KAKAO_REFRESH_TOKEN 값을 갱신하세요."
        )
    return payload


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
        data={"template_object": _to_json(template_object)},
        timeout=10,
    )
    if response.status_code != 200:
        raise KakaoSendError(
            f"카카오톡 발송 실패 (status={response.status_code}): {response.text}"
        )


def send_summary(rest_api_key: str, refresh_token: str, text: str, link_url: str) -> None:
    """요약 텍스트 메시지 1건을 상세 리포트 링크와 함께 발송한다."""
    token_payload = refresh_access_token(rest_api_key, refresh_token)
    send_text_to_me(token_payload["access_token"], text, link_url)


def _to_json(obj: dict) -> str:
    import json

    return json.dumps(obj, ensure_ascii=False)
