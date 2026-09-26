"""Canonical units, unit families and supply/demand period normalization.

Conversion factors are physical constants, not business configuration, so
they live in code. Quantities are compared only within one unit family and
on a common per-month basis (e.g. 2,000 t/month vs 500 t/week).
"""

from dataclasses import dataclass
from enum import StrEnum


class UnitFamily(StrEnum):
    MASS = "MASS"
    VOLUME = "VOLUME"
    ENERGY = "ENERGY"
    COUNT = "COUNT"


class QuantityUnit(StrEnum):
    KG = "kg"
    TONNE = "tonne"
    LITRE = "litre"
    M3 = "m3"
    KWH = "kWh"
    MWH = "MWh"
    GJ = "GJ"
    UNIT = "unit"


class Frequency(StrEnum):
    ONE_TIME = "ONE_TIME"
    DAY = "DAY"
    WEEK = "WEEK"
    MONTH = "MONTH"
    YEAR = "YEAR"


@dataclass(frozen=True)
class UnitDefinition:
    family: UnitFamily
    base_unit: QuantityUnit
    factor_to_base: float  # multiply a value in this unit by this to get base units


UNITS: dict[QuantityUnit, UnitDefinition] = {
    QuantityUnit.KG: UnitDefinition(UnitFamily.MASS, QuantityUnit.TONNE, 0.001),
    QuantityUnit.TONNE: UnitDefinition(UnitFamily.MASS, QuantityUnit.TONNE, 1.0),
    QuantityUnit.LITRE: UnitDefinition(UnitFamily.VOLUME, QuantityUnit.M3, 0.001),
    QuantityUnit.M3: UnitDefinition(UnitFamily.VOLUME, QuantityUnit.M3, 1.0),
    QuantityUnit.KWH: UnitDefinition(UnitFamily.ENERGY, QuantityUnit.MWH, 0.001),
    QuantityUnit.MWH: UnitDefinition(UnitFamily.ENERGY, QuantityUnit.MWH, 1.0),
    QuantityUnit.GJ: UnitDefinition(UnitFamily.ENERGY, QuantityUnit.MWH, 1 / 3.6),
    QuantityUnit.UNIT: UnitDefinition(UnitFamily.COUNT, QuantityUnit.UNIT, 1.0),
}

# Average Gregorian month: 365.25 / 12 days.
DAYS_PER_MONTH = 30.4375
PER_MONTH_FACTOR: dict[Frequency, float] = {
    Frequency.DAY: DAYS_PER_MONTH,
    Frequency.WEEK: DAYS_PER_MONTH / 7,
    Frequency.MONTH: 1.0,
    Frequency.YEAR: 1 / 12,
}


def unit_family(unit: QuantityUnit | str) -> UnitFamily:
    return UNITS[QuantityUnit(unit)].family


def same_family(a: QuantityUnit | str, b: QuantityUnit | str) -> bool:
    return unit_family(a) == unit_family(b)


def to_base(value: float, unit: QuantityUnit | str) -> float:
    return value * UNITS[QuantityUnit(unit)].factor_to_base


def base_unit(unit: QuantityUnit | str) -> QuantityUnit:
    return UNITS[QuantityUnit(unit)].base_unit


@dataclass(frozen=True)
class NormalizedQuantity:
    """A quantity in its family's base unit. ``per_month`` is None for one-time lots."""

    family: UnitFamily
    base_unit: QuantityUnit
    amount: float           # base units, as declared (per period or one-time total)
    per_month: float | None
    one_time: bool


def normalize(value: float, unit: QuantityUnit | str, frequency: Frequency | str) -> NormalizedQuantity:
    freq = Frequency(frequency)
    amount = to_base(value, unit)
    per_month = None if freq == Frequency.ONE_TIME else amount * PER_MONTH_FACTOR[freq]
    return NormalizedQuantity(unit_family(unit), base_unit(unit), amount, per_month, freq == Frequency.ONE_TIME)
