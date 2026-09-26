"""Curated material knowledge base (materials, properties, applications).

This is *data*, loaded into the database and editable through the admin API —
the matching engine never hard-codes material names.

Typical property ranges are indicative literature ranges for screening only.
The engine uses them solely as a clearly-labelled fallback when a listing has
no measured value, and doing so lowers the match's data confidence.
Application property rules are screening rules curated for this demo; they
must be confirmed against the applicable national standard before use.
"""

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.materials.models import (
    ApplicationType,
    Material,
    MaterialApplication,
    MaterialProperty,
    PhysicalState,
    PropertyDataType,
    PropertyDefinition,
)

INDICATIVE = "Indicative literature range for screening; provide measured values."
SCREENING = "Screening rule curated for the SYMBIO demo; confirm against the applicable standard."

# key, name, unit, valid_min, valid_max, aliases
PROPERTIES: list[tuple[str, str, str | None, float | None, float | None, list[str]]] = [
    ("sio2_pct", "Silica (SiO2)", "%", 0, 100, ["sio2", "sio₂", "silica", "silicon dioxide"]),
    ("cao_pct", "Lime (CaO)", "%", 0, 100, ["cao", "calcium oxide", "lime"]),
    ("al2o3_pct", "Alumina (Al2O3)", "%", 0, 100, ["al2o3", "al₂o₃", "alumina"]),
    ("fe2o3_pct", "Iron oxide (Fe2O3)", "%", 0, 100, ["fe2o3", "fe₂o₃", "iron oxide", "total iron"]),
    ("mgo_pct", "Magnesia (MgO)", "%", 0, 100, ["mgo", "magnesia", "magnesium oxide"]),
    ("so3_pct", "Sulphate (SO3)", "%", 0, 100, ["so3", "so₃", "sulphate", "sulfate", "sulphuric anhydride"]),
    ("loi_pct", "Loss on ignition", "%", 0, 100, ["loi", "loss on ignition", "l.o.i"]),
    ("free_lime_pct", "Free lime", "%", 0, 100, ["free lime", "free cao"]),
    ("moisture_pct", "Moisture", "%", 0, 100, ["moisture", "moisture content", "water content"]),
    ("particle_size_mm", "Maximum particle size", "mm", 0, 1000, ["particle size", "max size", "grain size"]),
    ("fineness_m2kg", "Blaine fineness", "m2/kg", 0, 2000, ["blaine", "fineness", "specific surface"]),
    ("bulk_density_t_m3", "Bulk density", "t/m3", 0, 25, ["bulk density", "density"]),
    ("ph", "pH", None, 0, 14, ["ph", "p.h."]),
    ("calorific_value_mj_kg", "Calorific value", "MJ/kg", 0, 60, ["calorific value", "gcv", "ncv", "heating value"]),
    ("organic_content_pct", "Organic matter", "%", 0, 100, ["organic matter", "organic content", "volatile solids"]),
    ("ash_content_pct", "Ash content", "%", 0, 100, ["ash", "ash content"]),
    ("temperature_c", "Temperature", "°C", -50, 1500, ["temperature", "temp"]),
    ("purity_pct", "Purity", "%", 0, 100, ["purity", "assay"]),
    ("chloride_pct", "Chloride", "%", 0, 100, ["chloride", "cl"]),
    ("heavy_metals_ppm", "Total heavy metals", "ppm", 0, 1_000_000, ["heavy metals", "total heavy metals"]),
    ("fiber_length_mm", "Fibre length", "mm", 0, 500, ["fibre length", "fiber length", "staple length"]),
    ("cellulose_pct", "Cellulose", "%", 0, 100, ["cellulose"]),
]

# canonical_name, category, subcategory, state, description, synonyms, typical ranges {key: (min, max)}
MATERIALS = [
    ("Steel Slag", "Metallurgical slag", "Steel slag", PhysicalState.SOLID,
     "Slag from basic oxygen (BOF/LD) or electric arc (EAF) steelmaking.",
     ["steel slag", "bof slag", "ld slag", "eaf slag", "converter slag", "steelmaking slag"],
     {"cao_pct": (40, 52), "sio2_pct": (10, 18), "fe2o3_pct": (15, 30), "mgo_pct": (3, 10), "free_lime_pct": (1, 10)}),
    ("Granulated Blast Furnace Slag", "Metallurgical slag", "Blast furnace slag", PhysicalState.SOLID,
     "Glassy slag from rapid water quenching of molten iron blast-furnace slag.",
     ["gbfs", "ggbs", "ggbfs", "granulated slag", "blast furnace slag", "water quenched slag", "bf slag"],
     {"sio2_pct": (30, 38), "cao_pct": (34, 42), "al2o3_pct": (10, 18), "mgo_pct": (5, 12)}),
    ("Fly Ash", "Combustion residue", "Coal ash", PhysicalState.SOLID,
     "Fine ash captured from flue gas of pulverised-coal boilers.",
     ["fly ash", "pulverised fuel ash", "pfa", "coal fly ash", "class f fly ash", "class c fly ash"],
     {"sio2_pct": (50, 65), "al2o3_pct": (20, 30), "fe2o3_pct": (4, 10), "cao_pct": (1, 8), "loi_pct": (0.5, 5)}),
    ("Bottom Ash", "Combustion residue", "Coal ash", PhysicalState.SOLID,
     "Coarse ash collected at the bottom of coal-fired boilers.",
     ["bottom ash", "boiler ash", "furnace bottom ash", "pond ash"],
     {"sio2_pct": (45, 60), "loi_pct": (1, 12)}),
    ("Limestone", "Natural mineral", "Carbonate rock", PhysicalState.SOLID,
     "Virgin calcium carbonate rock (cement raw mix, fluxing, aggregate).",
     ["limestone", "calcium carbonate", "caco3"], {"cao_pct": (45, 55)}),
    ("Natural Aggregate", "Natural mineral", "Aggregate", PhysicalState.SOLID,
     "Virgin crushed stone, gravel or sand for construction.",
     ["crushed stone", "stone aggregate", "gravel", "virgin aggregate", "river sand"], {}),
    ("Recycled Aggregate", "Construction & demolition", "Recycled aggregate", PhysicalState.SOLID,
     "Processed construction and demolition waste (crushed concrete, masonry).",
     ["recycled aggregate", "recycled concrete aggregate", "rca", "c&d waste", "demolition waste"], {}),
    ("Spent Foundry Sand", "Metallurgical residue", "Foundry sand", PhysicalState.SOLID,
     "Silica sand discarded from metal-casting moulds.",
     ["foundry sand", "waste foundry sand", "green sand", "spent sand"], {"sio2_pct": (80, 95)}),
    ("Organic Residue", "Organic residue", "Food processing residue", PhysicalState.SLUDGE,
     "Biodegradable residues from food and beverage processing.",
     ["food waste", "fruit pulp", "vegetable waste", "press mud", "organic waste", "spent grain", "whey"],
     {"moisture_pct": (60, 90), "organic_content_pct": (70, 95)}),
    ("Biomass Residue", "Organic residue", "Agricultural residue", PhysicalState.SOLID,
     "Dry agricultural residues such as husk, bagasse and straw.",
     ["rice husk", "bagasse", "straw", "crop residue", "husk", "agro residue", "wood chips"],
     {"calorific_value_mj_kg": (12, 17), "moisture_pct": (8, 15), "ash_content_pct": (3, 20)}),
    ("Paper Sludge", "Pulp & paper residue", "Paper sludge", PhysicalState.SLUDGE,
     "Fibre- and filler-rich sludge from paper mill effluent treatment or de-inking.",
     ["paper mill sludge", "deinking sludge", "etp sludge", "primary sludge", "paper sludge"],
     {"moisture_pct": (40, 70), "organic_content_pct": (30, 60), "cellulose_pct": (20, 50)}),
    ("Textile Fibre Waste", "Textile residue", "Fibre waste", PhysicalState.SOLID,
     "Pre-consumer fibre, yarn and fabric scraps from spinning, weaving and garmenting.",
     ["cotton waste", "textile waste", "yarn waste", "fabric scraps", "comber noil", "fibre waste", "fiber waste"],
     {"fiber_length_mm": (5, 30)}),
    ("Low-grade Waste Heat", "Energy stream", "Waste heat", PhysicalState.ENERGY,
     "Recoverable heat in exhaust gas, cooling water or steam condensate.",
     ["waste heat", "flue gas heat", "hot water", "process heat", "exhaust heat", "steam condensate"], {}),
    ("Phosphogypsum", "Chemical by-product", "Gypsum", PhysicalState.SOLID,
     "Calcium sulphate by-product of phosphoric acid production.",
     ["phosphogypsum", "by-product gypsum", "chemical gypsum", "synthetic gypsum"],
     {"so3_pct": (38, 45), "moisture_pct": (10, 25)}),
    ("Natural Gypsum", "Natural mineral", "Gypsum", PhysicalState.SOLID,
     "Mined calcium sulphate dihydrate.", ["gypsum", "mineral gypsum"], {"so3_pct": (40, 46)}),
    ("Brick Clay", "Natural mineral", "Clay", PhysicalState.SOLID,
     "Virgin clay/soil used for fired bricks.", ["clay", "brick earth", "topsoil"], {}),
]

# key, name, description, sectors
APPLICATIONS = [
    ("cement_blending", "Supplementary cementitious material",
     "Partial replacement of clinker/cement in blended cement or concrete.", ["Cement", "Construction"]),
    ("clinker_raw_mix", "Clinker raw-mix component",
     "CaO/SiO2/Al2O3/Fe2O3 source in cement kiln raw meal.", ["Cement"]),
    ("road_subbase", "Road base / sub-base",
     "Unbound granular layers in road construction.", ["Construction", "Infrastructure"]),
    ("concrete_aggregate", "Concrete aggregate", "Coarse or fine aggregate in concrete.", ["Construction"]),
    ("brick_making", "Brick and block manufacturing",
     "Raw material or additive for fired clay, fly-ash or concrete bricks/blocks.", ["Building materials"]),
    ("biogas_feedstock", "Biogas feedstock", "Anaerobic digestion substrate.", ["Energy", "Agriculture"]),
    ("solid_fuel", "Solid fuel / co-firing", "Boiler or kiln fuel substitute.", ["Energy", "Manufacturing", "Cement"]),
    ("composting", "Composting / soil amendment", "Feedstock for compost or soil conditioner.", ["Agriculture"]),
    ("insulation_fiber", "Insulation and non-woven fibre",
     "Fibre input for insulation batts, felts and non-woven products.", ["Building materials", "Textiles"]),
    ("process_heating", "Process heating",
     "Low-temperature heat for drying, pre-heating or space heating.", ["Food processing", "Chemicals"]),
    ("cement_set_retarder", "Cement set retarder", "Gypsum added to clinker to control setting.", ["Cement"]),
]


def _rule(key: str, lo: float | None = None, hi: float | None = None, importance: str = "REQUIRED") -> dict:
    return {"property_key": key, "min": lo, "max": hi, "importance": importance}


# material, application, description, required property rules
MATERIAL_APPLICATIONS = [
    ("Granulated Blast Furnace Slag", "cement_blending", "Ground GBFS as slag cement / concrete SCM.",
     [_rule("mgo_pct", hi=17), _rule("sio2_pct", lo=28, importance="PREFERRED")]),
    ("Granulated Blast Furnace Slag", "road_subbase", "Granulated slag in granular layers.", []),
    ("Fly Ash", "cement_blending", "Fly ash as pozzolana in PPC / concrete.",
     [_rule("loi_pct", hi=5), _rule("sio2_pct", lo=35), _rule("so3_pct", hi=3, importance="PREFERRED")]),
    ("Fly Ash", "brick_making", "Fly-ash bricks and blocks.", [_rule("loi_pct", hi=10, importance="PREFERRED")]),
    ("Fly Ash", "road_subbase", "Embankment and stabilised sub-base.", []),
    ("Bottom Ash", "road_subbase", "Fill and sub-base material.", []),
    ("Bottom Ash", "brick_making", "Partial replacement of clay/sand in bricks.", []),
    ("Steel Slag", "road_subbase", "Weathered steel slag aggregate for road layers.",
     [_rule("free_lime_pct", hi=4), _rule("particle_size_mm", hi=75, importance="PREFERRED")]),
    ("Steel Slag", "concrete_aggregate", "Aged steel slag as aggregate (volume stability critical).",
     [_rule("free_lime_pct", hi=2)]),
    ("Steel Slag", "clinker_raw_mix", "CaO and iron source in kiln raw meal.",
     [_rule("cao_pct", lo=35, importance="PREFERRED")]),
    ("Recycled Aggregate", "road_subbase", "Recycled aggregate in sub-base.", []),
    ("Recycled Aggregate", "concrete_aggregate", "Recycled coarse aggregate (partial replacement).", []),
    ("Spent Foundry Sand", "concrete_aggregate", "Partial fine-aggregate replacement.", []),
    ("Spent Foundry Sand", "brick_making", "Sand component in bricks/blocks.", []),
    ("Organic Residue", "biogas_feedstock", "Wet organic substrate for digesters.",
     [_rule("organic_content_pct", lo=50, importance="PREFERRED")]),
    ("Organic Residue", "composting", "Compost feedstock.", []),
    ("Biomass Residue", "solid_fuel", "Boiler fuel / co-firing.",
     [_rule("calorific_value_mj_kg", lo=10), _rule("moisture_pct", hi=25, importance="PREFERRED")]),
    ("Biomass Residue", "composting", "Carbon-rich compost input.", []),
    ("Paper Sludge", "brick_making", "Pore-forming additive in fired clay bricks.",
     [_rule("moisture_pct", hi=70, importance="PREFERRED")]),
    ("Paper Sludge", "solid_fuel", "Dewatered sludge as low-grade fuel.", [_rule("calorific_value_mj_kg", lo=5)]),
    ("Paper Sludge", "composting", "Fibre-rich compost input.", []),
    ("Textile Fibre Waste", "insulation_fiber", "Recycled fibre for insulation/non-wovens.",
     [_rule("fiber_length_mm", lo=5, importance="PREFERRED")]),
    ("Textile Fibre Waste", "solid_fuel", "Refuse-derived fuel component.", []),
    ("Low-grade Waste Heat", "process_heating", "Heat recovery for drying or pre-heating.", []),
    ("Phosphogypsum", "cement_set_retarder", "Treated phosphogypsum as set retarder.",
     [_rule("so3_pct", lo=35), _rule("moisture_pct", hi=15, importance="PREFERRED")]),
    ("Natural Gypsum", "cement_set_retarder", "Mineral gypsum set retarder.", []),
    ("Limestone", "clinker_raw_mix", "Primary CaO source.", [_rule("cao_pct", lo=44, importance="PREFERRED")]),
    ("Natural Aggregate", "road_subbase", "Virgin crushed stone sub-base.", []),
    ("Natural Aggregate", "concrete_aggregate", "Virgin aggregate for concrete.", []),
    ("Brick Clay", "brick_making", "Primary brick raw material.", []),
]


def seed_knowledge_base(db: Session) -> None:
    """Idempotent upsert of the curated knowledge base."""
    props = {p.key: p for p in db.scalars(select(PropertyDefinition))}
    for key, name, unit, lo, hi, aliases in PROPERTIES:
        prop = props.get(key) or PropertyDefinition(key=key)
        prop.name, prop.unit, prop.valid_min, prop.valid_max, prop.aliases = name, unit, lo, hi, aliases
        prop.data_type = PropertyDataType.NUMERIC
        db.add(prop)
        props[key] = prop
    db.flush()

    materials = {m.canonical_name: m for m in db.scalars(select(Material))}
    for name, category, subcategory, state, description, synonyms, typical in MATERIALS:
        material = materials.get(name) or Material(canonical_name=name)
        material.category, material.subcategory, material.physical_state = category, subcategory, state
        material.description, material.synonyms = description, synonyms
        db.add(material)
        db.flush()
        existing = {mp.property_id: mp for mp in material.properties}
        for key, (lo, hi) in typical.items():
            mp = existing.get(props[key].id) or MaterialProperty(material_id=material.id, property_id=props[key].id)
            mp.typical_min, mp.typical_max, mp.note = lo, hi, INDICATIVE
            db.add(mp)
        materials[name] = material
    db.flush()

    app_types = {a.key: a for a in db.scalars(select(ApplicationType))}
    for key, name, description, sectors in APPLICATIONS:
        app_type = app_types.get(key) or ApplicationType(key=key)
        app_type.name, app_type.description, app_type.applicable_industry_sectors = name, description, sectors
        db.add(app_type)
        app_types[key] = app_type
    db.flush()

    links = {(ma.material_id, ma.application_type_id): ma for ma in db.scalars(select(MaterialApplication))}
    for material_name, app_key, description, rules in MATERIAL_APPLICATIONS:
        material, app_type = materials[material_name], app_types[app_key]
        link = links.get((material.id, app_type.id)) or MaterialApplication(
            material_id=material.id, application_type_id=app_type.id)
        link.description, link.required_properties = description, rules
        link.source_note = SCREENING if rules else None
        db.add(link)
    db.commit()

    from app.seed.processing import seed_processing_knowledge  # processed products depend on the base catalogue

    seed_processing_knowledge(db)
