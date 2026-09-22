from fastapi import APIRouter, Depends, HTTPException, Request, Response, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core import ratelimit
from app.core.config import settings
from app.core.db import get_session
from app.core.deps import COOKIE_NAME, get_current_user
from app.core.security import create_access_token, dummy_verify, verify_password
from app.models.user import User
from app.schemas.auth import LoginRequest, TokenResponse, UserOut

router = APIRouter(prefix="/api/auth", tags=["auth"])


@router.post("/login", response_model=TokenResponse)
async def login(
    payload: LoginRequest,
    request: Request,
    response: Response,
    session: AsyncSession = Depends(get_session),
) -> TokenResponse:
    # ประตูหน้าบ้านต้องมีเพดานการลอง ไม่งั้นเดารหัสผ่านได้ไม่จำกัด
    # นับทุกครั้งที่เรียกรวมถึงครั้งที่สำเร็จ เพราะคนทั่วไปล็อกอินวันละไม่กี่ครั้ง
    email = payload.email.lower()

    # ชั้นที่หนึ่ง นับต่อ IP — เข้มงวด จับคนที่ยิงรัวจากที่เดียว
    await ratelimit.enforce(
        request,
        scope="login",
        limit=settings.rate_limit_login_attempts,
        window_seconds=settings.rate_limit_login_window_seconds,
    )

    # ชั้นที่สอง นับต่ออีเมล — หลวมกว่า เป็นตาข่ายรับคนที่หมุน IP หนีชั้นแรก
    #
    # ต้องมีทั้งสองชั้น ไม่ใช่เลือกอย่างใดอย่างหนึ่ง: ชั้น IP อย่างเดียวหลุดเมื่อ
    # ผู้โจมตีมี IP หลายตัว ส่วนชั้นอีเมลอย่างเดียวเปิดช่องให้ยิงรหัสผิดใส่บัญชี
    # คนอื่นจนเขาเข้าไม่ได้ · เมื่อชั้นอีเมลหลวมกว่ามาก การกลั่นแกล้งจึงแพงเกินคุ้ม
    # ขณะที่การเดารหัสยังชนชั้น IP ก่อนเสมอ
    #
    # แฮชอีเมลก่อนใช้เป็นคีย์ เพื่อไม่ให้ Redis กลายเป็นรายชื่ออีเมลที่มีคนพยายามเข้า
    await ratelimit.enforce(
        request,
        scope="login-email",
        limit=settings.rate_limit_login_attempts_per_email,
        window_seconds=settings.rate_limit_login_email_window_seconds,
        subject=ratelimit.opaque_subject(email),
    )

    result = await session.execute(select(User).where(User.email == email))
    user = result.scalar_one_or_none()

    # ตอบข้อความเดียวกันทั้งกรณีไม่มี user และรหัสผิด ไม่ให้เดาได้ว่าอีเมลไหนมีอยู่จริง
    #
    # แต่ข้อความเหมือนกันอย่างเดียวไม่พอ ถ้าไม่มี user แล้วไม่เรียก bcrypt เลย
    # คำตอบจะกลับเร็วกว่ากรณีมี user หลายสิบเท่า (bcrypt จงใจช้า) ผู้โจมตีจับเวลา
    # แล้วไล่ได้ว่าอีเมลไหนมีบัญชีอยู่จริง จึงต้องเผาเวลาให้เท่ากันด้วย
    if user is None:
        dummy_verify(payload.password)
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED, detail="อีเมลหรือรหัสผ่านไม่ถูกต้อง"
        )
    if not verify_password(payload.password, user.password_hash):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED, detail="อีเมลหรือรหัสผ่านไม่ถูกต้อง"
        )
    if not user.is_active:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="บัญชีถูกปิดใช้งาน")

    token = create_access_token(str(user.id), user.role)
    response.set_cookie(
        key=COOKIE_NAME,
        value=token,
        httponly=True,
        samesite="lax",
        secure=settings.cookie_secure,
        max_age=settings.access_token_expire_minutes * 60,
        path="/",
    )
    return TokenResponse(access_token=token)


@router.post("/logout", status_code=status.HTTP_204_NO_CONTENT)
async def logout(response: Response) -> None:
    response.delete_cookie(COOKIE_NAME, path="/")


@router.get("/me", response_model=UserOut)
async def me(user: User = Depends(get_current_user)) -> User:
    return user
