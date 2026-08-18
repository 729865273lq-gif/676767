from __future__ import annotations

import asyncio
import math
import re
from uuid import uuid4
from urllib.parse import urlparse

from sqlalchemy.orm import Session

from app.agents.base.contracts import AgentRunContext, SearchResult
from app.agents.customer.models import CustomerDiscoveryInput, CustomerDiscoveryOutput
from app.connectors.search import SearchConnector
from app.crm.scoring import qualify_lead
from app.crm.service import LeadService
from app.platform.product_lines import ProductLineService
from app.platform.search_keywords import KeywordPlan
from app.platform.service import OrganizationService
from app.workflow.models import WorkflowState
from app.workflow.service import WorkflowService

PRODUCT_SEARCH_ALIASES = (
    ("轴承座", "bearing housing"),
    ("轴承", "bearing"),
    ("紧固件", "fastener"),
    ("阀门", "industrial valve"),
    ("电机", "electric motor"),
    ("电缆", "cable"),
    ("汽配", "auto parts"),
    ("家具", "furniture"),
    ("服装", "apparel"),
    ("纺织", "textile"),
    ("五金", "hardware"),
    ("灯具", "lighting"),
    ("机械", "machinery"),
    ("建材", "building materials"),
)
PRODUCT_QUERY_EXPANSIONS = {
    "bearing": (
        "bearing",
        "bearing housing",
        "pillow block bearing",
        "mounted bearing unit",
        "plummer block",
    ),
    "lighting": ("lighting", "industrial lighting", "LED lighting", "commercial lighting"),
    "fastener": ("fastener", "industrial fasteners", "bolts and nuts"),
    "industrial valve": ("industrial valve", "process valve", "flow control valve"),
    "electric motor": ("electric motor", "industrial motor", "AC motor"),
    "auto parts": ("auto parts", "automotive spare parts", "vehicle parts"),
}
BUYER_SEARCH_ALIASES = (
    ("生产", "manufacturer"),
    ("制造", "manufacturer"),
    ("销售", "distributor"),
    ("经销", "distributor"),
    ("批发", "wholesaler"),
    ("进口", "importer"),
    ("采购", "buyer"),
    ("代理", "agent"),
)
MARKET_SEARCH_ALIASES = {
    "越南": "Vietnam",
    "胡志明市": "Ho Chi Minh City Vietnam",
    "河内": "Hanoi Vietnam",
    "泰国": "Thailand",
    "马来西亚": "Malaysia",
    "印度尼西亚": "Indonesia",
    "菲律宾": "Philippines",
    "新加坡": "Singapore",
    "印度": "India",
    "美国": "United States",
    "加拿大": "Canada",
    "英国": "United Kingdom",
    "德国": "Germany",
    "法国": "France",
    "意大利": "Italy",
    "西班牙": "Spain",
    "荷兰": "Netherlands",
    "波兰": "Poland",
    "匈牙利": "Hungary",
    "土耳其": "Turkey",
    "阿联酋": "United Arab Emirates",
    "沙特阿拉伯": "Saudi Arabia",
    "俄罗斯": "Russia",
    "日本": "Japan",
    "韩国": "South Korea",
    "澳大利亚": "Australia",
    "墨西哥": "Mexico",
    "巴西": "Brazil",
    "南非": "South Africa",
}
MARKET_CITY_EXPANSIONS = {
    "Malaysia": (
        "Kuala Lumpur Malaysia",
        "Selangor Malaysia",
        "Johor Bahru Malaysia",
        "Penang Malaysia",
        "Ipoh Malaysia",
        "Kota Kinabalu Malaysia",
        "Kuching Malaysia",
    ),
    "Vietnam": ("Ho Chi Minh City Vietnam", "Hanoi Vietnam", "Da Nang Vietnam", "Hai Phong Vietnam"),
    "Thailand": ("Bangkok Thailand", "Chonburi Thailand", "Rayong Thailand", "Chiang Mai Thailand"),
    "Indonesia": ("Jakarta Indonesia", "Surabaya Indonesia", "Bandung Indonesia", "Medan Indonesia"),
    "Philippines": ("Metro Manila Philippines", "Cebu Philippines", "Davao Philippines"),
    "India": ("Mumbai India", "Delhi India", "Bengaluru India", "Chennai India", "Ahmedabad India"),
    "United States": ("Houston United States", "Chicago United States", "Los Angeles United States", "Dallas United States"),
    "Germany": ("Berlin Germany", "Hamburg Germany", "Munich Germany", "Frankfurt Germany"),
    "United Kingdom": ("London United Kingdom", "Birmingham United Kingdom", "Manchester United Kingdom"),
    "United Arab Emirates": ("Dubai United Arab Emirates", "Abu Dhabi United Arab Emirates", "Sharjah United Arab Emirates"),
    "Saudi Arabia": ("Riyadh Saudi Arabia", "Jeddah Saudi Arabia", "Dammam Saudi Arabia"),
    "Australia": ("Sydney Australia", "Melbourne Australia", "Brisbane Australia", "Perth Australia"),
    "Mexico": ("Mexico City Mexico", "Monterrey Mexico", "Guadalajara Mexico"),
    "Brazil": ("Sao Paulo Brazil", "Rio de Janeiro Brazil", "Belo Horizonte Brazil"),
    "South Africa": ("Johannesburg South Africa", "Cape Town South Africa", "Durban South Africa"),
}

DEFAULT_BUYER_TERMS = ("distributor", "wholesaler", "importer", "industrial supplier", "MRO supplier")
GENERIC_SOURCE_HOSTS = {
    "openstreetmap.org",
    "tomtom.com",
    "geoapify.com",
    "foursquare.com",
}


class CustomerAgent:
    agent_id = "customer"
    version = "1.1.0"
    input_model = CustomerDiscoveryInput
    output_model = CustomerDiscoveryOutput

    def __init__(
        self,
        session: Session,
        search_connector: SearchConnector,
        keyword_provider=None,
    ):
        self.session = session
        self.search_connector = search_connector
        self._keyword_provider = keyword_provider

    async def run(
        self, context: AgentRunContext, payload: CustomerDiscoveryInput
    ) -> CustomerDiscoveryOutput:
        product_line = ProductLineService(self.session).get_product_line(
            payload.product_line_id, context.organization_id
        )
        excluded_keywords = [*product_line.excluded_keywords, *payload.excluded_keywords]
        keyword_plan = None
        if self._keyword_provider is not None:
            keyword_plan = self._keyword_provider(
                self.session, product_line, payload.location_country_code
            )
        queries = build_discovery_queries(
            product_line.name,
            product_line.product_keywords,
            payload,
            excluded_keywords=excluded_keywords,
            keyword_plan=keyword_plan,
        )
        per_query_limit = min(payload.limit, 30, max(8, math.ceil(payload.limit / len(queries))))
        batches = await run_search_queries(self.search_connector, queries, per_query_limit)
        candidate_count = sum(len(results) for _, results, _ in batches)
        failed_query_count = sum(1 for _, _, error in batches if error is not None)
        successful_batches = [(query, results) for query, results, error in batches if error is None]
        if not successful_batches:
            errors = "; ".join(str(error) for _, _, error in batches if error is not None)
            raise RuntimeError(f"all customer search queries failed: {errors}")
        results, duplicate_count = merge_discovery_results(successful_batches)
        product_aliases = matching_search_aliases(
            f"{product_line.name} {' '.join(product_line.product_keywords)}",
            PRODUCT_SEARCH_ALIASES,
        )
        relevance_terms = product_relevance_terms(
            [*product_aliases, *product_query_terms(product_line.name, product_line.product_keywords)]
        )
        lead_service = LeadService(self.session)
        lead_ids: list[str] = []
        filtered_count = 0
        overflow_count = 0
        for result in results:
            if search_result_matches_exclusions(result, excluded_keywords):
                filtered_count += 1
                continue
            if len(lead_ids) >= payload.limit:
                overflow_count += 1
                continue
            if relevance_terms and not search_result_matches_terms(result, relevance_terms):
                filtered_count += 1
                continue
            contact_channels = [
                channel
                for channel, value in {
                    "email": result.email,
                    "phone": result.phone,
                    "whatsapp": result.whatsapp,
                    "social": result.social_profiles,
                }.items()
                if value
            ]
            qualification = qualify_lead(
                website=result.url,
                fit_evidence=[result.snippet] if result.snippet else [],
                contact_channels=contact_channels,
                decision_maker_attempted=False,
            )
            lead = lead_service.save_discovered_lead(
                organization_id=context.organization_id,
                workflow_run_id=context.workflow_run_id,
                product_line_id=product_line.id,
                target_market=payload.target_market,
                buyer_profile=payload.buyer_profile,
                result=result,
                qualification=qualification,
            )
            if lead.id not in lead_ids:
                lead_ids.append(lead.id)
        return CustomerDiscoveryOutput(
            workflow_run_id=context.workflow_run_id,
            query=queries[0],
            lead_count=len(lead_ids),
            lead_ids=lead_ids,
            filtered_count=filtered_count,
            query_count=len(queries),
            queries=queries,
            candidate_count=candidate_count,
            duplicate_count=duplicate_count,
            overflow_count=overflow_count,
            failed_query_count=failed_query_count,
        )


class CustomerDiscoveryInProgress(RuntimeError):
    """Raised when an idempotent discovery request is already executing."""


class CustomerDiscoveryService:
    def __init__(
        self,
        session: Session,
        search_connector: SearchConnector,
        keyword_provider=None,
    ):
        self.session = session
        self.agent = CustomerAgent(session, search_connector, keyword_provider=keyword_provider)

    async def start(
        self,
        *,
        actor_user_id: str,
        organization_id: str,
        payload: CustomerDiscoveryInput,
        idempotency_key: str | None = None,
    ) -> CustomerDiscoveryOutput:
        OrganizationService(self.session).require_membership(actor_user_id, organization_id)
        workflow_service = WorkflowService(self.session)
        run = workflow_service.create_run(
            organization_id=organization_id,
            agent_id=self.agent.agent_id,
            agent_version=self.agent.version,
            input_payload=payload.model_dump(),
            idempotency_key=idempotency_key or str(uuid4()),
        )
        if run.state == WorkflowState.COMPLETED and run.output_json is not None:
            return CustomerDiscoveryOutput.model_validate(run.output_json)
        if run.state == WorkflowState.RUNNING:
            raise CustomerDiscoveryInProgress("customer discovery is already running")
        if run.state == WorkflowState.FAILED:
            workflow_service.transition(run.id, WorkflowState.QUEUED, organization_id=organization_id)
        if run.state == WorkflowState.QUEUED:
            workflow_service.transition(run.id, WorkflowState.RUNNING, organization_id=organization_id)
        try:
            output = await self.agent.run(
                AgentRunContext(organization_id=organization_id, workflow_run_id=run.id), payload
            )
        except Exception as error:
            workflow_service.transition(
                run.id,
                WorkflowState.FAILED,
                organization_id=organization_id,
                error_code="customer_discovery_failed",
                error_detail=str(error)[:500],
            )
            raise
        workflow_service.transition(
            run.id,
            WorkflowState.COMPLETED,
            organization_id=organization_id,
            output_payload=output.model_dump(),
        )
        return output


def build_discovery_query(
    product_line_name: str,
    keywords: list[str],
    payload: CustomerDiscoveryInput,
) -> str:
    product_source = f"{product_line_name} {' '.join(keywords[:5])}".strip()
    product_aliases = matching_search_aliases(product_source, PRODUCT_SEARCH_ALIASES)
    product_terms = " ".join(product_aliases) or (" ".join(keywords[:5]) or product_line_name)

    buyer_source = payload.buyer_profile or "buyer"
    buyer_aliases = matching_search_aliases(buyer_source, BUYER_SEARCH_ALIASES)
    buyer_terms = " ".join(buyer_aliases) or buyer_source
    market_terms = MARKET_SEARCH_ALIASES.get(payload.target_market.strip(), payload.target_market)
    return f"{product_terms} {buyer_terms} {market_terms}".strip()


def build_discovery_queries(
    product_line_name: str,
    keywords: list[str],
    payload: CustomerDiscoveryInput,
    *,
    excluded_keywords: list[str] | None = None,
    keyword_plan: KeywordPlan | None = None,
) -> list[str]:
    if keyword_plan is not None:
        return _build_multilingual_queries(product_line_name, keywords, payload, keyword_plan)
    query_limit = 4 if payload.limit <= 20 else 6 if payload.limit <= 50 else 8
    primary_query = build_discovery_query(product_line_name, keywords, payload)
    products = product_query_terms(product_line_name, keywords)
    buyers = buyer_query_terms(payload.buyer_profile, excluded_keywords or [])
    markets = market_query_terms(payload.target_market)
    queries: list[str] = []

    def add(query: str) -> None:
        normalized = " ".join(query.split())
        if normalized and normalized.casefold() not in {item.casefold() for item in queries}:
            queries.append(normalized)

    add(primary_query)
    for index, product in enumerate(products[1:3], start=1):
        add(f"{product} {buyers[index % len(buyers)]} {markets[0]}")
    for index, buyer in enumerate(buyers[1:3], start=1):
        add(f"{products[index % len(products)]} {buyer} {markets[0]}")
    city_index = 1
    while len(queries) < query_limit and city_index < len(markets):
        product = products[city_index % len(products)]
        buyer = buyers[city_index % len(buyers)]
        add(f"{product} {buyer} {markets[city_index]}")
        city_index += 1
    fallback_index = 0
    while len(queries) < query_limit:
        product = products[fallback_index % len(products)]
        buyer = buyers[(fallback_index + 1) % len(buyers)]
        add(f"{product} {buyer} {markets[0]}")
        fallback_index += 1
        if fallback_index > len(products) * len(buyers):
            break
    return queries[:query_limit]


def _build_multilingual_queries(
    product_line_name: str,
    keywords: list[str],
    payload: CustomerDiscoveryInput,
    keyword_plan: KeywordPlan,
) -> list[str]:
    query_limit = 4 if payload.limit <= 20 else 6 if payload.limit <= 50 else 8
    markets = market_query_terms(payload.target_market)
    market = markets[0]
    queries: list[str] = []

    def add(query: str) -> None:
        normalized = " ".join(query.split())
        if normalized and normalized.casefold() not in {item.casefold() for item in queries}:
            queries.append(normalized)

    for keyword in [*keyword_plan.localized, *keyword_plan.english]:
        add(f"{keyword} {market}")
    first_localized = keyword_plan.localized[0] if keyword_plan.localized else ""
    for city in markets[1:]:
        if first_localized:
            add(f"{first_localized} {city}")
    return queries[:query_limit]


def product_query_terms(product_line_name: str, keywords: list[str]) -> list[str]:
    source = f"{product_line_name} {' '.join(keywords)}".strip()
    aliases = matching_search_aliases(source, PRODUCT_SEARCH_ALIASES)
    terms: list[str] = []
    source_casefold = source.casefold()
    for key, expansion in PRODUCT_QUERY_EXPANSIONS.items():
        if key.casefold() in source_casefold:
            terms.extend(expansion)
    for alias in aliases:
        expansion = next(
            (values for key, values in PRODUCT_QUERY_EXPANSIONS.items() if key in alias),
            (alias,),
        )
        terms.extend(expansion)
    for value in [*keywords, product_line_name]:
        terms.extend(part.strip() for part in re.split(r"[,，;；]", value) if part.strip())
    return unique_terms(terms)[:6] or [product_line_name]


def buyer_query_terms(buyer_profile: str | None, excluded_keywords: list[str]) -> list[str]:
    aliases = matching_search_aliases(buyer_profile or "", BUYER_SEARCH_ALIASES)
    excluded = [value.casefold() for value in excluded_keywords if value.strip()]
    terms = [*aliases, *DEFAULT_BUYER_TERMS]
    return [
        term
        for term in unique_terms(terms)
        if not any(
            term.casefold() in exclusion or exclusion in term.casefold()
            for exclusion in excluded
        )
    ] or ["buyer"]


def market_query_terms(target_market: str) -> list[str]:
    market = MARKET_SEARCH_ALIASES.get(target_market.strip(), target_market.strip())
    return [market, *MARKET_CITY_EXPANSIONS.get(market, ())]


async def run_search_queries(
    connector: SearchConnector,
    queries: list[str],
    limit: int,
) -> list[tuple[str, list[SearchResult], Exception | None]]:
    semaphore = asyncio.Semaphore(2)

    async def run(query: str) -> tuple[str, list[SearchResult], Exception | None]:
        async with semaphore:
            try:
                return query, await connector.search(query, limit), None
            except Exception as error:
                return query, [], error

    return list(await asyncio.gather(*(run(query) for query in queries)))


def merge_discovery_results(
    batches: list[tuple[str, list[SearchResult]]],
) -> tuple[list[SearchResult], int]:
    merged: list[SearchResult] = []
    identity_to_index: dict[str, int] = {}
    duplicate_count = 0
    for _, results in batches:
        for result in results:
            identities = result_identity_keys(result)
            existing_index = next(
                (identity_to_index[key] for key in identities if key in identity_to_index),
                None,
            )
            if existing_index is None:
                existing_index = len(merged)
                merged.append(result)
            else:
                duplicate_count += 1
                merged[existing_index] = merge_search_result(merged[existing_index], result)
            for key in result_identity_keys(merged[existing_index]):
                identity_to_index[key] = existing_index
    return merged, duplicate_count


def result_identity_keys(result: SearchResult) -> set[str]:
    keys: set[str] = set()
    if result.canonical_key.strip():
        keys.add(f"canonical:{result.canonical_key.strip().casefold()}")
    host = website_host(result.url)
    if host and host not in GENERIC_SOURCE_HOSTS:
        keys.add(f"host:{host}")
    phone = re.sub(r"\D", "", result.phone)
    if len(phone) >= 7:
        keys.add(f"phone:{phone}")
    title = re.sub(r"[^a-z0-9]+", "", result.title.casefold())
    if len(title) >= 5:
        keys.add(f"title:{title}")
    return keys or {f"url:{result.url.strip().casefold()}"}


def merge_search_result(current: SearchResult, incoming: SearchResult) -> SearchResult:
    current_host = website_host(current.url)
    incoming_host = website_host(incoming.url)
    incoming_has_website = bool(incoming_host and incoming_host not in GENERIC_SOURCE_HOSTS)
    current_has_website = bool(current_host and current_host not in GENERIC_SOURCE_HOSTS)
    preferred = incoming if incoming_has_website and not current_has_website else current
    other = current if preferred is incoming else incoming
    canonical_key = preferred.canonical_key
    if incoming_has_website and not current_has_website:
        canonical_key = incoming_host
    return preferred.model_copy(
        update={
            "canonical_key": canonical_key,
            "snippet": preferred.snippet or other.snippet,
            "email": preferred.email or other.email,
            "phone": preferred.phone or other.phone,
            "whatsapp": preferred.whatsapp or other.whatsapp,
            "social_profiles": preferred.social_profiles or other.social_profiles,
            "source_url": preferred.source_url or other.source_url,
        }
    )


def website_host(url: str) -> str:
    parsed = urlparse(url if "://" in url else f"https://{url}")
    return parsed.netloc.casefold().removeprefix("www.")


def unique_terms(values: list[str] | tuple[str, ...]) -> list[str]:
    unique: list[str] = []
    seen: set[str] = set()
    for value in values:
        normalized = " ".join(value.split())
        key = normalized.casefold()
        if normalized and key not in seen:
            seen.add(key)
            unique.append(normalized)
    return unique


def matching_search_aliases(source: str, aliases: tuple[tuple[str, str], ...]) -> list[str]:
    matches: list[str] = []
    for source_term, search_term in aliases:
        if source_term in source and search_term not in matches:
            matches.append(search_term)
    return matches


def product_relevance_terms(product_aliases: list[str]) -> set[str]:
    terms: set[str] = set()
    for alias in product_aliases:
        normalized = alias.casefold().strip()
        if normalized:
            terms.add(normalized)
        terms.update(term for term in normalized.split() if len(term) >= 4)
    return terms


def search_result_matches_terms(result: SearchResult, relevance_terms: set[str]) -> bool:
    searchable = f"{result.title} {result.snippet} {result.url}".lower()
    return any(term in searchable for term in relevance_terms)


def search_result_matches_exclusions(result: SearchResult, excluded_keywords: list[str]) -> bool:
    searchable = f"{result.title} {result.snippet} {result.url}".casefold()
    return any(
        keyword.strip().casefold() in searchable
        for keyword in excluded_keywords
        if keyword.strip()
    )
