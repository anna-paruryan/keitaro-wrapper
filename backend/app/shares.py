"""Расчёт долей (share) офферов в потоке.

Keitaro хочет, чтобы доли офферов в потоке в сумме давали 100. Все функции здесь
возвращают целые числа с суммой ровно 100 (метод наибольшего остатка), поэтому
после любой правки цифры в интерфейсе и в Keitaro совпадают.
"""

import math
from collections.abc import Sequence
from typing import Optional

TOTAL = 100


def allocate(weights: Sequence[float], total: int = TOTAL) -> list[int]:
    """Раскладывает `total` по весам пропорционально; сумма результата всегда равна `total`."""
    n = len(weights)
    if n == 0:
        return []
    w = [max(float(x), 0.0) for x in weights]
    s = sum(w)
    if s <= 0:
        w, s = [1.0] * n, float(n)
    raw = [x * total / s for x in w]
    base = [math.floor(r) for r in raw]
    rest = total - sum(base)
    # Остаток раздаём тем, у кого дробная часть больше; при равенстве - тому, кто выше в списке
    order = sorted(range(n), key=lambda i: (-(raw[i] - base[i]), i))
    for i in order[:rest]:
        base[i] += 1
    return base


def shares_equal(n: int) -> list[int]:
    """Поровну: 3 оффера -> [34, 33, 33]."""
    return allocate([1.0] * n)


def distribute(pinned: Sequence[Optional[int]], total: int = TOTAL) -> list[int]:
    """Доли с «пинами». На входе по одному элементу на оффер:

    * число - закреплённая доля, она не меняется;
    * None - свободный оффер: все свободные делят остаток поровну.

    distribute([None, None, None])  -> [34, 33, 33]
    distribute([25, None, None])    -> [25, 38, 37]
    distribute([25, 25, 25, 25])    -> [25, 25, 25, 25]

    ValueError, если расчёт невозможен (тогда сообщение можно показать пользователю).
    """
    if not pinned:
        return []
    free = [i for i, p in enumerate(pinned) if p is None]
    fixed = sum(p for p in pinned if p is not None)
    if free:
        left = total - fixed
        if left < len(free):
            raise ValueError("The pinned shares leave no room for the other offers. Unpin one of them first.")
        parts = iter(allocate([1.0] * len(free), left))
        return [p if p is not None else next(parts) for p in pinned]
    if fixed != total:
        raise ValueError("All offers are pinned and their shares do not add up to 100%. Unpin one of the offers first.")
    return [int(p) for p in pinned]