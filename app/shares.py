"""Traffic share math for offers inside a stream. Shares are integers that sum to 100."""
from typing import Dict, List


def distribute_evenly(offer_ids: List[int]) -> Dict[int, int]:
    """Split 100% between offers as evenly as integers allow.

    The remainder goes to the first offers, one point each: 3 offers -> 34/33/33.
    """
    n = len(offer_ids)
    if n == 0:
        return {}
    base, rest = divmod(100, n)
    return {oid: base + (1 if i < rest else 0) for i, oid in enumerate(offer_ids)}


def validate_shares(shares: Dict[int, int]) -> None:
    if not shares:
        raise ValueError("В потоке должен остаться хотя бы один оффер")
    for oid, share in shares.items():
        if not 0 <= share <= 100:
            raise ValueError(f"Доля оффера {oid} должна быть от 0 до 100, сейчас {share}")
    total = sum(shares.values())
    if total != 100:
        raise ValueError(f"Сумма долей должна быть 100%, сейчас {total}%")


def rebalance(active_ids: List[int], pinned: Dict[int, int]) -> Dict[int, int]:
    """Recalculate shares of active offers, keeping pinned shares untouched.

    What's left after the pinned shares (100 - sum(pinned)) is split evenly between
    the unpinned offers by the same rule as distribute_evenly: 25 pinned + 3 free -> 25/25/25/25,
    40 pinned + 3 free -> 40/20/20/20, 50 pinned + 3 free -> 50/17/17/16.
    If every active offer is pinned, the shares are returned as is (the sum may differ from 100,
    and push refuses to publish such a stream).
    """
    pinned = {oid: share for oid, share in pinned.items() if oid in active_ids}
    pinned_total = sum(pinned.values())
    if pinned_total > 100:
        raise ValueError(f"Закреплённые доли в сумме {pinned_total}% — больше 100%")
    free = [oid for oid in active_ids if oid not in pinned]
    spread = {}
    if free:
        base, rest = divmod(100 - pinned_total, len(free))
        spread = {oid: base + (1 if i < rest else 0) for i, oid in enumerate(free)}
    return {oid: pinned[oid] if oid in pinned else spread[oid] for oid in active_ids}
