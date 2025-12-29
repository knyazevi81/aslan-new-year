from __future__ import annotations

from dataclasses import dataclass, field
from decimal import Decimal
from typing import Any, Dict, List, Optional


@dataclass
class PricingMultiplier:
    code: str
    value: Decimal
    note: Optional[str] = None


@dataclass
class PricingState:
    base_rate: Decimal = Decimal("0")
    factor_per_risk_unit: Decimal = Decimal("0")
    risk_weight_sum: int = 0
    deductible_discount: Decimal = Decimal("0")
    multipliers: List[PricingMultiplier] = field(default_factory=list)

    tariff_total: Decimal = Decimal("0")
    premium_total: int = 0

    @property
    def multipliers_product(self) -> Decimal:
        product = Decimal("1")
        for m in self.multipliers:
            product *= m.value
        return product

    def breakdown(self) -> Dict[str, Any]:
        return {
            "base_rate": str(self.base_rate),
            "multipliers": [
                {"code": m.code, "value": str(m.value), "note": m.note} for m in self.multipliers
            ],
            "multipliers_product": str(self.multipliers_product),
            "risk_weight_sum": self.risk_weight_sum,
            "factor_per_risk_unit": str(self.factor_per_risk_unit),
            "deductible_discount": str(self.deductible_discount),
            "tariff_total": str(self.tariff_total),
            "premium_total": self.premium_total,
        }
