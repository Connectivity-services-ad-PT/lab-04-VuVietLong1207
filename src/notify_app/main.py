import os
from datetime import datetime, timezone
from enum import Enum
from typing import Dict, List, Optional

from fastapi import Depends, FastAPI, Header, HTTPException, Query, Request, Response, status
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field

SERVICE_NAME = os.getenv("SERVICE_NAME", "notification-service")
SERVICE_VERSION = os.getenv("SERVICE_VERSION", "0.4.0")
AUTH_TOKEN = os.getenv("AUTH_TOKEN", "local-dev-token")
NOTIFY_PROVIDER_TOKEN = os.getenv("NOTIFY_PROVIDER_TOKEN", "mock_secret_token_abcd1234")

app = FastAPI(
    title="FIT4110 Lab 04 - Smart Campus Notification Service",
    version=SERVICE_VERSION,
    description=(
        "Dockerized Notification API aligned with the Lab 03 OpenAPI/Postman contract."
    ),
)


class NotificationChannel(str, Enum):
    email = "email"
    sms = "sms"
    fcm = "fcm"


class ProblemDetails(BaseModel):
    type: str = "about:blank"
    title: str
    status: int = Field(..., ge=400, le=599)
    detail: str
    instance: Optional[str] = None


class HealthResponse(BaseModel):
    status: str
    service: str
    version: str


class NotificationPayload(BaseModel):
    recipient: str = Field(
        ..., 
        min_length=3, 
        examples=["student01@dainam.edu.vn", "+84912345678"],
        description="Địa chỉ email hoặc số điện thoại định dạng chuẩn nhận thông báo."
    )
    channel: NotificationChannel = Field(..., examples=["email"])
    title: str = Field(
        ..., 
        min_length=1, 
        max_length=100, 
        description="Boundary check: Tiêu đề không vượt quá 100 ký tự.",
        examples=["Cảnh báo nhiệt độ phòng Lab A01"]
    )
    body: str = Field(..., min_length=1, examples=["Phòng Lab A01 vượt ngưỡng 31.5°C."])


class NotificationCreatedResponse(BaseModel):
    notification_id: str
    recipient: str
    channel: NotificationChannel
    status: str
    created_at: str


NOTIFICATIONS_LOG: List[Dict] = []


def build_problem(
    *,
    status_code: int,
    title: str,
    detail: str,
    instance: Optional[str] = None,
    problem_type: str = "about:blank",
) -> Dict:
    problem = {
        "type": problem_type,
        "title": title,
        "status": status_code,
        "detail": detail,
    }
    if instance:
        problem["instance"] = instance
    return problem


@app.exception_handler(HTTPException)
async def http_exception_handler(request: Request, exc: HTTPException) -> JSONResponse:
    if isinstance(exc.detail, dict):
        problem = exc.detail
    else:
        problem = build_problem(
            status_code=exc.status_code,
            title=status.HTTP_STATUS_CODES.get(exc.status_code, "HTTP Error"),
            detail=str(exc.detail),
            instance=str(request.url.path),
        )

    problem.setdefault("status", exc.status_code)
    problem.setdefault("title", status.HTTP_STATUS_CODES.get(exc.status_code, "HTTP Error"))
    problem.setdefault("type", "about:blank")
    problem.setdefault("detail", "Request failed")
    problem.setdefault("instance", str(request.url.path))

    return JSONResponse(
        status_code=exc.status_code,
        content=problem,
        media_type="application/problem+json",
        headers=getattr(exc, "headers", None),
    )


@app.exception_handler(RequestValidationError)
async def validation_exception_handler(
    request: Request, exc: RequestValidationError
) -> JSONResponse:
    first_error = exc.errors()[0] if exc.errors() else {}
    location = ".".join(str(item) for item in first_error.get("loc", []))
    message = first_error.get("msg", "Request validation error")
    detail = f"{location}: {message}" if location else message

    return JSONResponse(
        status_code=status.HTTP_400_BAD_REQUEST,
        content=build_problem(
            status_code=status.HTTP_400_BAD_REQUEST,
            title="Bad Request - Invalid Payload",
            detail=f"Dữ liệu truyền vào không vượt qua bộ lọc kiểm tra: {detail}",
            instance=str(request.url.path),
            problem_type="https://smart-campus.local/problems/validation-error",
        ),
        media_type="application/problem+json",
    )


def verify_bearer_token(authorization: Optional[str] = Header(default=None)) -> None:
    if not authorization:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail=build_problem(
                status_code=status.HTTP_401_UNAUTHORIZED,
                title="Unauthorized",
                detail="Missing Authorization header",
                problem_type="https://smart-campus.local/problems/unauthorized",
            ),
        )

    expected = f"Bearer {AUTH_TOKEN}"
    if authorization != expected:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail=build_problem(
                status_code=status.HTTP_401_UNAUTHORIZED,
                title="Unauthorized",
                detail="Invalid bearer token",
                problem_type="https://smart-campus.local/problems/unauthorized",
            ),
        )


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def next_notification_id() -> str:
    today = datetime.now(timezone.utc).strftime("%Y%m%d")
    return f"NTF-{today}-{len(NOTIFICATIONS_LOG) + 1:04d}"


@app.get("/health", response_model=HealthResponse)
def health() -> HealthResponse:
    return HealthResponse(
        status="ok",
        service=SERVICE_NAME,
        version=SERVICE_VERSION,
    )


@app.post(
    "/api/v1/notifications",
    response_model=NotificationCreatedResponse,
    status_code=status.HTTP_202_ACCEPTED,
    dependencies=[Depends(verify_bearer_token)],
    responses={
        401: {"model": ProblemDetails},
        400: {"model": ProblemDetails},
    },
)
def create_notification(payload: NotificationPayload) -> NotificationCreatedResponse:
    notification_id = next_notification_id()
    created_at = now_iso()

    if NOTIFY_PROVIDER_TOKEN == "mock_secret_token_abcd1234":
        print(f"[MOCK PROVIDER LOG] Gửi kênh [{payload.channel.value}] đến <{payload.recipient}> thành công!")

    item = {
        "notification_id": notification_id,
        "recipient": payload.recipient,
        "channel": payload.channel.value,
        "title": payload.title,
        "body": payload.body,
        "status": "sent" if NOTIFY_PROVIDER_TOKEN != "mock_secret_token_abcd1234" else "mocked",
        "created_at": created_at,
    }
    NOTIFICATIONS_LOG.append(item)

    return NotificationCreatedResponse(
        notification_id=notification_id,
        recipient=payload.recipient,
        channel=payload.channel,
        status=item["status"],
        created_at=created_at,
    )


@app.get("/api/v1/notifications/history", dependencies=[Depends(verify_bearer_token)])
def get_notification_history(
    channel: Optional[NotificationChannel] = Query(default=None),
    limit: int = Query(default=10, ge=1, le=100),
) -> Dict[str, List[Dict]]:
    items = NOTIFICATIONS_LOG

    if channel:
        items = [item for item in items if item["channel"] == channel.value]

    return {"items": items[-limit:]}


@app.get("/api/v1/notifications/{notification_id}", dependencies=[Depends(verify_bearer_token)])
def get_single_notification(notification_id: str) -> Dict:
    for item in NOTIFICATIONS_LOG:
        if item["notification_id"] == notification_id:
            return item

    raise HTTPException(
        status_code=status.HTTP_404_NOT_FOUND,
        detail=build_problem(
            status_code=status.HTTP_404_NOT_FOUND,
            title="Not Found",
            detail=f"Notification with ID {notification_id} does not exist",
            instance=f"/api/v1/notifications/{notification_id}",
            problem_type="https://smart-campus.local/problems/not-found",
        ),
    )