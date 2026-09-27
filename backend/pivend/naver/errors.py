SEARCHAD_NOT_CONFIGURED = (
    "네이버 검색광고 API 키가 연결되지 않았어요. 설정 > API 연결에서 검색광고 API 키를 등록해 주세요."
)
OPENAPI_NOT_CONFIGURED = (
    "네이버 개발자센터 API 키가 연결되지 않았어요. 설정 > API 연결에서 Client ID/Secret을 등록해 주세요."
)


class NaverError(Exception):
    """Base error for Naver API calls."""


class NaverNotConfigured(NaverError):
    """Raised when the credentials for an API are missing."""


class NaverAPIError(NaverError):
    def __init__(self, message: str, status_code: int | None = None, body: str | None = None):
        super().__init__(message)
        self.status_code = status_code
        self.body = body
