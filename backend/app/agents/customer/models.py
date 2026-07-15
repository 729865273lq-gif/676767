from pydantic import BaseModel, Field


class CustomerDiscoveryInput(BaseModel):
    product_line_id: str = Field(min_length=1)
    target_market: str = Field(min_length=1, max_length=120)
    buyer_profile: str | None = Field(default=None, max_length=200)
    limit: int = Field(default=20, ge=1, le=50)


class CustomerDiscoveryOutput(BaseModel):
    workflow_run_id: str
    query: str
    lead_count: int
