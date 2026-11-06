"""Documented unit evidence and bounded precision research, never execution rules.

Reviewed 2026-11-06. Native CLOB minimum units, fee rounding direction and
per-match aggregation remain unverified; a source's USDC label is not proof
of the actual collateral token used by a particular protocol/market.
"""
from decimal import Decimal, ROUND_FLOOR, ROUND_CEILING
from market.event_details import decimal

MARKET_DOC = "https://docs.polymarket.com/market-data/market-details"
FEE_DOC = "https://docs.polymarket.com/trading/fees"
FEE_QUANTUM = Decimal("0.00001")


def unit_evidence(market, params):
    minimum = decimal(market.get("minimum_size"), "Gamma最小名义金额")
    tick = decimal(market.get("price_tick"), "Gamma价格档位")
    if minimum <= 0 or minimum != params["minimum"] or tick != params["tick"]:
        raise ValueError("Gamma与CLOB最小值或价格档位不一致，不能合并单位进行成本研究")
    return dict(reviewed_on="2026-11-06", gamma_minimum_notional=float(minimum),
        gamma_minimum_unit="USDC", gamma_minimum_source=MARKET_DOC,
        native_clob_minimum_unit=None, native_unit_verified=False,
        fee_precision_decimals=5, fee_precision_quantum=str(FEE_QUANTUM), fee_precision_source=FEE_DOC,
        fee_rounding_direction_verified=False, fee_match_aggregation_verified=False,
        collateral_asset=None, collateral_asset_verified=False,
        blockers=["CLOB原生最小值单位尚未核验", "实际抵押资产及协议映射尚未核验",
                  "实际扣费方向、逐笔撮合与取整汇总尚未核验"],
        simulation_ready=False, execution_enabled=False)


def precision_envelope(fee):
    """Bounds for ONE modeled level treated as ONE match, not actual fees.

    The published minimum says sub-quantum fees become zero; otherwise no
    undocumented tie-breaking is chosen. Real matching can split levels.
    """
    if fee < 0:
        raise ValueError("费用估计不能为负")
    if fee < FEE_QUANTUM:
        return Decimal(0), Decimal(0)
    return (fee.quantize(FEE_QUANTUM, rounding=ROUND_FLOOR),
            fee.quantize(FEE_QUANTUM, rounding=ROUND_CEILING))
