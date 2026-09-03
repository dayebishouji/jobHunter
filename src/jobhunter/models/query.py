"""Query — the user-supplied input to a single run."""

from __future__ import annotations

from pydantic import BaseModel, Field


class CompanyQuery(BaseModel):
    """A user-provided target for reverse due-diligence.

    All fields except `company` are optional. Position/city help with search
    precision but the system must run on bare company name alone.
    """

    company: str = Field(..., min_length=1, max_length=200, description="公司名（必填）")
    position: str = Field(default="", max_length=200, description="岗位（可选）")
    city: str = Field(default="", max_length=100, description="城市（可选）")
    include_judicial: bool = Field(default=True, description="是否抓司法风险")
    include_news: bool = Field(default=True, description="是否抓近期舆情")
    aliases: list[str] = Field(
        default_factory=list,
        description="LLM 自动生成的常见缩写 / 英文名 / 子品牌（用于 reviews 域查询展开）",
    )

    def display(self) -> str:
        parts = [self.company]
        if self.position:
            parts.append(self.position)
        if self.city:
            parts.append(self.city)
        return " · ".join(parts)
