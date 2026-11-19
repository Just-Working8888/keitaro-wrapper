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
