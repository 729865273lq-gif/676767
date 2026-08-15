from pydantic import BaseModel, Field


class CustomerDiscoveryInput(BaseModel):
    product_line_id: str = Field(min_length=1)
    target_market: str = Field(min_length=1, max_length=120)
    location_scope_id: str = Field(default="", max_length=300)
    location_country_code: str = Field(default="", max_length=3)
    allow_repeat_location: bool = False
    buyer_profile: str | None = Field(default=None, max_length=200)
    excluded_keywords: list[str] = Field(default_factory=list, max_length=100)
    limit: int = Field(default=50, ge=1, le=200)


class CustomerDiscoveryOutput(BaseModel):
    workflow_run_id: str
    query: str
    lead_count: int
    lead_ids: list[str] = Field(default_factory=list)
    filtered_count: int = 0
    query_count: int = 1
    queries: list[str] = Field(default_factory=list)
    candidate_count: int = 0
    duplicate_count: int = 0
    overflow_count: int = 0
    failed_query_count: int = 0
