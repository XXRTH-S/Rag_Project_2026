"""Client ของ HF Text-Embeddings-Inference (bge-m3 บน CPU)

bge-m3 รองรับไทยดีและให้เวกเตอร์ 1024 มิติ ตรงกับคอลัมน์ VECTOR(1024) ใน migration
"""
import httpx

from app.core.config import settings


class EmbeddingClient:
    def __init__(self, base_url: str | None = None, api_key: str | None = None) -> None:
        self.base_url = (base_url or settings.embedding_base_url).rstrip("/")
        self.api_key = api_key if api_key is not None else settings.embedding_api_key

    def _headers(self) -> dict[str, str]:
        headers = {"Content-Type": "application/json"}
        if self.api_key:
            headers["Authorization"] = f"Bearer {self.api_key}"
        return headers

    async def embed(self, texts: list[str], *, timeout: int = 120) -> list[list[float]]:
        if not texts:
            return []
        async with httpx.AsyncClient(timeout=timeout) as client:
            resp = await client.post(
                f"{self.base_url}/embed",
                json={"inputs": texts, "truncate": True},
                headers=self._headers(),
            )
            resp.raise_for_status()
            vectors = resp.json()

        for vec in vectors:
            if len(vec) != settings.embedding_dim:
                raise ValueError(
                    f"embedding มี {len(vec)} มิติ แต่ตาราง chunks ประกาศไว้ "
                    f"{settings.embedding_dim} — เปลี่ยนโมเดล embedding ต้องเขียน migration ใหม่"
                )
        return vectors

    async def embed_one(self, text: str, *, timeout: int = 60) -> list[float]:
        return (await self.embed([text], timeout=timeout))[0]

    async def health(self) -> bool:
        try:
            async with httpx.AsyncClient(timeout=5) as client:
                resp = await client.get(f"{self.base_url}/health")
                return resp.status_code == 200
        except httpx.HTTPError:
            return False
