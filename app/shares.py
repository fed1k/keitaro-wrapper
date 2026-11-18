"""Share (weight) math for offers inside a stream.

Keitaro requires offer shares in a stream to be integers that sum to 100.
"""


def split_evenly(offer_ids: list[int]) -> dict[int, int]:
    """Distribute 100% evenly; the remainder goes to the first offers.

    3 offers -> 34/33/33, 6 offers -> 17/17/17/17/16/16.
    """
    n = len(offer_ids)
    if n == 0:
        return {}
    base, rest = divmod(100, n)
    return {oid: base + (1 if i < rest else 0) for i, oid in enumerate(offer_ids)}


def validate_shares(shares: dict[int, int]) -> None:
    if not shares:
        raise ValueError("В потоке должен остаться хотя бы один оффер")
    if any(s < 0 or s > 100 for s in shares.values()):
        raise ValueError("Доля должна быть от 0 до 100")
    total = sum(shares.values())
    if total != 100:
        raise ValueError(f"Сумма долей должна быть 100%, сейчас {total}%")
