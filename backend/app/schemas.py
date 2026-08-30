from pydantic import BaseModel, Field


class CreateStokvelRequest(BaseModel):
    name: str = Field(min_length=2, max_length=120)
    monthly_amount: float = Field(gt=0)
    contribution_day: int = Field(ge=1, le=28)
    creator_member_id: int


class JoinStokvelRequest(BaseModel):
    member_id: int


class CreateContributionRequest(BaseModel):
    member_id: int
    stokvel_id: int
    amount: float = Field(gt=0)
    contribution_month: str = Field(pattern=r"^\d{4}-\d{2}$")
