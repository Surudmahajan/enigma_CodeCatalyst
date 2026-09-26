"""Multi-industry demo dataset, created through the real services so every
validation, event and matching run happens exactly as in production.

Scenarios included (see README "Demo scenario"):
  * ABC Steel -> XYZ Construction: steel slag, 2,000 vs 1,500 t/month, ~82 km (the polished demo, left DISCOVERED)
  * Hidden matches via applications: GBFS / fly ash -> cement blending; paper sludge / fly ash -> bricks
  * Partial coverage (Konkan Aggregates), very distant demand (Chennai), processing gap (Vidarbha -> Quick Build)
  * Filtered out: property mismatch (Metro Roads), no date overlap (Pune Metro), expired listing (Vidarbha)
  * Energy stream: waste heat -> process heating
  * Semantic-only candidate needing manual review (unlinked furnace residue)
  * A completed exchange with impact records (FreshHarvest -> BioUrja) and a pending connection (Shakti -> ABC)
Demo accounts share the password from SEED_DEMO_PASSWORD.
"""

from dataclasses import dataclass, field
from datetime import date, timedelta
from decimal import Decimal
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.common.listing_schemas import PropertyConstraintIn, PropertyValueIn
from app.common.listings import ListingStatus
from app.connections import service as connections
from app.core.config import get_settings
from app.core.dependencies import OrgContext, resolve_org_context
from app.core.security import hash_password
from app.exchanges import service as exchanges
from app.exchanges.models import ExchangeStatus
from app.exchanges.schemas import ExchangeCreate
from app.materials.models import ApplicationType, Material
from app.matching.models import Match
from app.messaging import service as messaging
from app.organizations import service as orgs
from app.organizations.models import Organization, VerificationStatus
from app.organizations.schemas import LocationIn, OrganizationCreate
from app.requirements import service as requirements
from app.requirements.schemas import RequirementCreate
from app.resources import service as resources
from app.resources.models import Resource
from app.resources.schemas import ResourceCreate
from app.users.models import User

DOMAIN = "demo.example.com"


@dataclass
class OrgSeed:
    key: str
    display_name: str
    sector: str
    mode: str
    city: str
    state: str
    lat: float
    lon: float
    description: str
    owner: tuple[str, str]
    verified: bool = True
    resources: list[dict[str, Any]] = field(default_factory=list)
    requirements: list[dict[str, Any]] = field(default_factory=list)


def _props(**values: float) -> list[PropertyValueIn]:
    return [PropertyValueIn(property_key=k, value_numeric=v) for k, v in values.items()]


def _limit(key: str, lo: float | None = None, hi: float | None = None, importance: str = "REQUIRED"):
    return PropertyConstraintIn(property_key=key, min_value=lo, max_value=hi, importance=importance)


TODAY = date.today()
IN_1Y = TODAY + timedelta(days=365)

ORGS: list[OrgSeed] = [
    OrgSeed("abc", "ABC Steel", "Steel manufacturing", "BOTH", "Chakan, Pune", "Maharashtra", 18.7400, 73.8190,
            "Integrated steel plant producing flat products; BOF and blast furnace operations.", ("Priya", "Kulkarni"),
            resources=[
                dict(material="Steel Slag", name="BOF steel slag (weathered)",
                     description="LD converter slag, weathered 6+ months in open yard. XRF data available.",
                     quantity_available=2000, frequency="MONTH", processing_required=True,
                     processing_types=["crushing"], processing_description="Crushing and screening to 0-40 mm.",
                     current_disposition="DISPOSAL", disposal_cost_per_unit=350, processing_cost_per_unit=120,
                     properties=_props(free_lime_pct=2.5, moisture_pct=6, cao_pct=44, fe2o3_pct=22)),
                dict(material="Granulated Blast Furnace Slag", name="Granulated blast furnace slag",
                     description="Water-quenched glassy slag from BF-2, dried, suitable for grinding.",
                     quantity_available=3000, frequency="MONTH", current_disposition="LOW_VALUE_USE",
                     asking_price_per_unit=450, properties=_props(sio2_pct=34, cao_pct=39, mgo_pct=8.5, al2o3_pct=14)),
            ],
            requirements=[
                dict(material="Limestone", name="Flux-grade limestone", quantity_required=800, frequency="MONTH",
                     description="Limestone for sinter plant fluxing.", virgin_material_price_per_unit=1400,
                     constraints=[_limit("cao_pct", lo=48)]),
            ]),
    OrgSeed("xyz", "XYZ Construction", "Construction", "DEMANDER", "Taloja, Navi Mumbai", "Maharashtra",
            19.0660, 73.1170, "Highway and industrial-park contractor.", ("Rahul", "Deshmukh"),
            requirements=[
                dict(material="Steel Slag", application="road_subbase", name="Steel slag aggregate for road sub-base",
                     description="Granular sub-base for 18 km industrial corridor road. Crushing on site possible.",
                     quantity_required=1500, frequency="MONTH", max_transport_distance_km=150,
                     processing_capabilities=["crushing", "screening"], virgin_material_price_per_unit=900,
                     constraints=[_limit("free_lime_pct", hi=4), _limit("moisture_pct", hi=10, importance="PREFERRED")],
                     until=TODAY + timedelta(days=300)),
            ]),
    OrgSeed("shakti", "Shakti Cement", "Cement", "DEMANDER", "Ahmednagar", "Maharashtra", 19.0948, 74.7480,
            "Cement plant producing PPC and PSC.", ("Anita", "Joshi"),
            requirements=[
                dict(application="cement_blending", name="Supplementary cementitious material for PSC/PPC",
                     description="Any SCM meeting blended-cement chemistry; grinding available at plant.",
                     quantity_required=5000, frequency="MONTH", processing_capabilities=["grinding", "drying"],
                     virgin_material_price_per_unit=2200,
                     constraints=[_limit("mgo_pct", hi=17), _limit("sio2_pct", lo=28, importance="PREFERRED")]),
            ]),
    OrgSeed("greenpower", "GreenPower Thermal", "Power generation", "PROVIDER", "Nashik", "Maharashtra",
            20.0110, 73.7903, "Coal-fired thermal power station.", ("Vikram", "Patil"),
            resources=[
                dict(material="Fly Ash", name="Dry fly ash (ESP)", description="Class F fly ash from ESP hoppers.",
                     quantity_available=12000, frequency="MONTH", current_disposition="STORAGE",
                     disposal_cost_per_unit=150, properties=_props(sio2_pct=58, loi_pct=3.2, mgo_pct=1.5, so3_pct=0.8)),
            ]),
    OrgSeed("deccan", "Deccan Bricks", "Building materials", "DEMANDER", "Hadapsar, Pune", "Maharashtra",
            18.5089, 73.9260, "Fired clay and fly-ash brick manufacturer.", ("Sunil", "Pawar"),
            requirements=[
                dict(application="brick_making", material="Brick Clay", name="Raw material for fired bricks",
                     description="Clay substitute or pore-forming additive for kiln-fired bricks.",
                     quantity_required=600, frequency="MONTH", virgin_material_price_per_unit=700),
            ]),
    OrgSeed("sahyadri", "Sahyadri Paper Mills", "Pulp & paper", "PROVIDER", "Satara", "Maharashtra",
            17.6805, 74.0183, "Recycled-fibre paper mill.", ("Meera", "Shinde"),
            resources=[
                dict(material="Paper Sludge", name="Primary ETP sludge (dewatered)",
                     description="Fibre and calcium carbonate filler sludge from effluent treatment, belt-press dewatered.",
                     quantity_available=400, frequency="MONTH", current_disposition="DISPOSAL",
                     disposal_cost_per_unit=900, properties=_props(moisture_pct=55, organic_content_pct=42)),
            ]),
    OrgSeed("freshharvest", "FreshHarvest Foods", "Food processing", "BOTH", "Baramati", "Maharashtra",
            18.1519, 74.5815, "Fruit and vegetable processing.", ("Kavita", "More"),
            resources=[
                dict(material="Organic Residue", name="Fruit and vegetable processing residue",
                     description="Peels, pulp and rejects from juice and pulp lines.", quantity_available=250,
                     frequency="MONTH", physical_state="SLUDGE", current_disposition="DISPOSAL",
                     disposal_cost_per_unit=600, properties=_props(moisture_pct=82, organic_content_pct=90)),
            ],
            requirements=[
                dict(material="Low-grade Waste Heat", application="process_heating", name="Process heat for dryers",
                     description="Hot water/steam for fruit dehydration line.", quantity_required=300, unit="MWh",
                     frequency="MONTH"),
            ]),
    OrgSeed("biourja", "BioUrja Energy", "Renewable energy", "DEMANDER", "Daund", "Maharashtra", 18.4634, 74.5850,
            "Compressed biogas plant.", ("Arjun", "Gaikwad"),
            requirements=[
                dict(material="Organic Residue", application="biogas_feedstock", name="Wet organic feedstock for digesters",
                     quantity_required=300, frequency="MONTH", virgin_material_price_per_unit=400,
                     constraints=[_limit("organic_content_pct", lo=60, importance="PREFERRED")]),
            ]),
    OrgSeed("kalyani", "Kalyani Chemicals", "Chemicals", "PROVIDER", "Kurkumbh MIDC", "Maharashtra", 18.3950, 74.5210,
            "Specialty chemicals with exothermic processes.", ("Nikhil", "Rao"),
            resources=[
                dict(material="Low-grade Waste Heat", name="Cooling-water waste heat (85 °C)",
                     description="Recoverable heat from reactor cooling circuit.", quantity_available=500, unit="MWh",
                     frequency="MONTH", physical_state="ENERGY", current_disposition="OTHER",
                     properties=_props(temperature_c=85)),
            ]),
    OrgSeed("konkan", "Konkan Aggregates", "Construction", "DEMANDER", "Panvel", "Maharashtra", 18.9894, 73.1175,
            "Aggregate trader supplying ready-mix plants.", ("Rohan", "Naik"),
            requirements=[
                dict(material="Steel Slag", name="Slag aggregate (bulk)", quantity_required=5000, frequency="MONTH",
                     processing_capabilities=["crushing"], virgin_material_price_per_unit=850,
                     constraints=[_limit("free_lime_pct", hi=4)]),
            ]),
    OrgSeed("chennai", "Chennai Infra Builders", "Construction", "DEMANDER", "Chennai", "Tamil Nadu", 13.0827, 80.2707,
            "Road contractor in Tamil Nadu.", ("Lakshmi", "Iyer"),
            requirements=[
                dict(material="Steel Slag", application="road_subbase", name="Slag for road sub-base (Chennai ring road)",
                     quantity_required=1000, frequency="MONTH", processing_capabilities=["crushing"],
                     virgin_material_price_per_unit=950, constraints=[_limit("free_lime_pct", hi=4)]),
            ]),
    OrgSeed("metroroads", "Metro Roads", "Construction", "DEMANDER", "Pimpri, Pune", "Maharashtra", 18.6298, 73.7997,
            "Urban road maintenance contractor.", ("Farhan", "Shaikh"),
            requirements=[  # REQUIRED free lime <= 1 %: ABC's slag (2.5 %) is correctly filtered out.
                dict(material="Steel Slag", name="Volume-stable slag for concrete paving", quantity_required=500,
                     frequency="MONTH", constraints=[_limit("free_lime_pct", hi=1)]),
            ]),
    OrgSeed("punemetro", "Pune Metro Contractors", "Infrastructure", "DEMANDER", "Pune", "Maharashtra", 18.5204,
            73.8567, "Metro phase 3 civil works consortium.", ("Sneha", "Kale"),
            requirements=[  # Starts after ABC's slag window ends: no timing overlap.
                dict(material="Steel Slag", name="Slag fill for depot (phase 3)", quantity_required=1200,
                     frequency="MONTH", start=IN_1Y + timedelta(days=60), until=IN_1Y + timedelta(days=400)),
            ]),
    OrgSeed("vidarbha", "Vidarbha Steel", "Steel manufacturing", "PROVIDER", "Jalna", "Maharashtra", 19.8347, 75.8816,
            "Mini steel plant with electric arc furnaces.", ("Ganesh", "Wagh"), verified=False,
            resources=[
                dict(material="Steel Slag", name="Unprocessed EAF slag", description="Fresh EAF slag lumps, unsorted.",
                     quantity_available=800, frequency="MONTH", processing_required=True,
                     processing_types=["crushing", "magnetic_separation"], current_disposition="STORAGE",
                     properties=_props(free_lime_pct=3.5)),
            ]),
    OrgSeed("quickbuild", "Quick Build Co", "Construction", "DEMANDER", "Aurangabad", "Maharashtra", 19.8762, 75.3433,
            "Small builder; no on-site processing equipment.", ("Imran", "Khan"),
            requirements=[
                dict(material="Steel Slag", application="road_subbase", name="Ready-to-use sub-base material",
                     quantity_required=400, frequency="MONTH", virgin_material_price_per_unit=950),
            ]),
    OrgSeed("ichalkaranji", "Ichalkaranji Textiles", "Textiles", "PROVIDER", "Ichalkaranji", "Maharashtra",
            16.6910, 74.4605, "Cotton spinning and weaving mill.", ("Pooja", "Chavan"),
            resources=[
                dict(material="Textile Fibre Waste", name="Comber noil and yarn waste",
                     description="Clean pre-consumer cotton fibre waste, baled.", quantity_available=80,
                     frequency="MONTH", current_disposition="LOW_VALUE_USE", asking_price_per_unit=12000,
                     properties=_props(fiber_length_mm=12)),
            ]),
    OrgSeed("thermofab", "ThermoFab Insulation", "Building materials", "DEMANDER", "Kolhapur", "Maharashtra",
            16.7050, 74.2433, "Non-woven insulation felt producer.", ("Aditya", "Jadhav"),
            requirements=[
                dict(application="insulation_fiber", name="Recycled fibre for insulation felt", quantity_required=60,
                     frequency="MONTH", virgin_material_price_per_unit=18000, max_price_per_unit=14000,
                     constraints=[_limit("fiber_length_mm", lo=8, importance="PREFERRED")]),
            ]),
    OrgSeed("deccanminerals", "Deccan Minerals", "Mining & quarrying", "PROVIDER", "Daund", "Maharashtra",
            18.4700, 74.5700, "Limestone quarry; fines are a by-product of aggregate crushing.", ("Tejas", "Mane"),
            resources=[  # Lets ABC Steel (BOTH) be a demander too: limestone for fluxing.
                dict(material="Limestone", name="Limestone fines (0-10 mm)",
                     description="Crusher fines too small for aggregate customers; high CaO.", quantity_available=1200,
                     frequency="MONTH", current_disposition="STORAGE", asking_price_per_unit=600,
                     properties=_props(cao_pct=51, moisture_pct=4)),
            ]),
    OrgSeed("bhosari", "Bhosari Castings", "Foundry", "PROVIDER", "Bhosari, Pune", "Maharashtra", 18.6270, 73.8480,
            "Grey-iron foundry.", ("Sameer", "Bhosale"),
            resources=[  # No normalized material: only semantic similarity links it (manual review).
                dict(material=None, name="Black granular furnace residue",
                     description="Sand-like black granular residue from cupola furnace, fine grained",
                     quantity_available=150, frequency="MONTH", current_disposition="DISPOSAL"),
            ]),
    OrgSeed("greenfill", "GreenFill Landscaping", "Landscaping", "DEMANDER", "Pune", "Maharashtra", 18.55, 73.90,
            "Landscaping and trench backfill works.", ("Neha", "Kamble"),
            requirements=[
                dict(material=None, name="Granular residue for trench backfill",
                     description="Fine grained sand-like granular residue for backfilling cable trenches",
                     quantity_required=100, frequency="MONTH"),
            ]),
]


def _ctx(db: Session, user: User, org: Organization) -> OrgContext:
    return resolve_org_context(db, user, org.id)


def _lookup(db: Session) -> tuple[dict[str, Material], dict[str, ApplicationType]]:
    return ({m.canonical_name: m for m in db.scalars(select(Material))},
            {a.key: a for a in db.scalars(select(ApplicationType))})


def seed_admin(db: Session) -> None:
    email = f"admin@{DOMAIN}"
    if db.scalars(select(User).where(User.email == email)).first():
        return
    db.add(User(email=email, password_hash=hash_password(get_settings().seed_demo_password), first_name="Platform",
                last_name="Admin", is_verified=True, is_platform_admin=True))
    db.commit()


def seed_organizations(db: Session) -> dict[str, tuple[User, Organization]]:
    materials, apps = _lookup(db)
    password = hash_password(get_settings().seed_demo_password)
    created: dict[str, tuple[User, Organization]] = {}
    for seed in ORGS:
        email = f"{seed.key}@{DOMAIN}"
        user = db.scalars(select(User).where(User.email == email)).first()
        if user is not None:
            org = user.memberships[0].organization
            created[seed.key] = (user, org)
            continue
        user = User(email=email, password_hash=password, first_name=seed.owner[0], last_name=seed.owner[1],
                    is_verified=True)
        db.add(user)
        db.commit()
        org = orgs.create_organization(db, user, OrganizationCreate(
            legal_name=f"{seed.display_name} Pvt Ltd", display_name=seed.display_name, industry_sector=seed.sector,
            description=seed.description, operating_mode=seed.mode, business_email=f"contact.{seed.key}@{DOMAIN}",
            business_phone="+91 20 5555 0100",
            headquarters=LocationIn(city=seed.city, state=seed.state, country="India", address=f"Plant, {seed.city}",
                                    latitude=seed.lat, longitude=seed.lon),
        ))
        org.verification_status = VerificationStatus.VERIFIED if seed.verified else VerificationStatus.PENDING
        db.commit()
        ctx = _ctx(db, user, org)
        facility_id = org.facilities[0].id
        for r in seed.resources:
            material = materials.get(r["material"]) if r.get("material") else None
            resources.create(db, ctx, ResourceCreate(
                facility_id=facility_id, material_id=material.id if material else None, name=r["name"],
                description=r.get("description"), quantity_available=r["quantity_available"],
                unit=r.get("unit", "tonne"), frequency=r["frequency"], availability_start=TODAY,
                availability_end=r.get("until", IN_1Y), physical_state=r.get("physical_state",
                                                                             material.physical_state if material else "SOLID"),
                processing_required=r.get("processing_required", False), processing_types=r.get("processing_types", []),
                processing_description=r.get("processing_description"),
                current_disposition=r.get("current_disposition", "DISPOSAL"),
                disposal_cost_per_unit=r.get("disposal_cost_per_unit"), asking_price_per_unit=r.get("asking_price_per_unit"),
                processing_cost_per_unit=r.get("processing_cost_per_unit"), properties=r.get("properties", []),
                publish=True,
            ))
        for q in seed.requirements:
            material = materials.get(q["material"]) if q.get("material") else None
            application = apps.get(q["application"]) if q.get("application") else None
            requirements.create(db, ctx, RequirementCreate(
                facility_id=facility_id, material_id=material.id if material else None,
                intended_application_id=application.id if application else None, name=q["name"],
                description=q.get("description"), quantity_required=q["quantity_required"], unit=q.get("unit", "tonne"),
                frequency=q["frequency"], required_from=q.get("start", TODAY), required_until=q.get("until"),
                max_transport_distance_km=q.get("max_transport_distance_km"),
                processing_capabilities=q.get("processing_capabilities", []),
                virgin_material_price_per_unit=q.get("virgin_material_price_per_unit"),
                max_price_per_unit=q.get("max_price_per_unit"), property_constraints=q.get("constraints", []),
                publish=True,
            ))
        created[seed.key] = (user, org)
    return created


def seed_expired_listing(db: Session, vidarbha: tuple[User, Organization]) -> None:
    user, org = vidarbha
    if db.scalars(select(Resource).where(Resource.name == "Old slag stockpile (2025 campaign)")).first():
        return
    steel_slag = db.scalars(select(Material).where(Material.canonical_name == "Steel Slag")).one()
    db.add(Resource(organization_id=org.id, facility_id=org.facilities[0].id, material_id=steel_slag.id,
                    created_by_user_id=user.id, name="Old slag stockpile (2025 campaign)", quantity_available=5000,
                    unit="tonne", frequency="ONE_TIME", availability_start=TODAY - timedelta(days=400),
                    availability_end=TODAY - timedelta(days=30), physical_state="SOLID",
                    current_disposition="STORAGE", status=ListingStatus.EXPIRED))
    db.commit()


def _match_between(db: Session, provider: Organization, demander: Organization) -> Match | None:
    return db.scalars(select(Match).where(Match.provider_org_id == provider.id, Match.demander_org_id == demander.id)
                      .order_by(Match.overall_score.desc())).first()


def seed_journeys(db: Session, orgs_by_key: dict[str, tuple[User, Organization]]) -> None:
    """A completed exchange (with impact) and a pending incoming request for ABC Steel."""
    fh_user, freshharvest = orgs_by_key["freshharvest"]
    bu_user, biourja = orgs_by_key["biourja"]
    match = _match_between(db, freshharvest, biourja)
    if match is not None and match.status.value in ("DISCOVERED", "VIEWED", "INTERESTED"):
        bu_ctx, fh_ctx = _ctx(db, bu_user, biourja), _ctx(db, fh_user, freshharvest)
        connection = connections.request_connection(db, bu_ctx, match.id,
                                                    "We can take all of your fruit residue for our digesters.")
        connections.accept(db, fh_ctx, connection.id)
        conversation = messaging.conversation_for_connection(db, connection.id)
        messaging.send_message(db, bu_ctx, conversation.id, "Could you share moisture and contamination data?")
        messaging.send_message(db, fh_ctx, conversation.id, "Moisture is about 82 %, no plastics. Lab report attached soon.")
        messaging.send_message(db, bu_ctx, conversation.id, "Great — proposing weekly pickups from next Monday.")
        exchange = exchanges.create(db, bu_ctx, match.id, ExchangeCreate(
            agreed_quantity=250, unit="tonne", agreed_frequency="MONTH", agreed_price_per_unit=0, currency="INR",
            start_date=TODAY - timedelta(days=90), end_date=TODAY, delivery_terms={"transport": "BioUrja tanker trucks"}))
        exchanges.change_status(db, bu_ctx, exchange.id, ExchangeStatus.IN_PROGRESS)
        exchanges.change_status(db, fh_ctx, exchange.id, ExchangeStatus.COMPLETED, "Pilot quarter completed",
                                Decimal(740))

    sh_user, shakti = orgs_by_key["shakti"]
    _abc_user, abc = orgs_by_key["abc"]
    gbfs_match = _match_between(db, abc, shakti)
    if gbfs_match is not None and gbfs_match.status.value in ("DISCOVERED", "VIEWED", "INTERESTED"):
        connections.request_connection(db, _ctx(db, sh_user, shakti), gbfs_match.id,
                                       "Your GBFS looks suitable for our PSC line. Can we discuss volumes?")


def seed_demo(db: Session) -> dict[str, int]:
    seed_admin(db)
    orgs_by_key = seed_organizations(db)
    seed_expired_listing(db, orgs_by_key["vidarbha"])
    seed_journeys(db, orgs_by_key)
    return {
        "organizations": len(orgs_by_key),
        "matches": len(list(db.scalars(select(Match.id)))),
    }
