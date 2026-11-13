"""Расчёт долей (share) офферов в потоке.

Keitaro хочет, чтобы доли офферов в потоке в сумме давали 100. Все функции здесь
возвращают целые числа с суммой ровно 100 (метод наибольшего остатка), поэтому
после любой правки цифры в интерфейсе и в Keitaro совпадают.
"""

import math
from collections.abc import Sequence

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
    # Остаток раздаём тем, у кого дробная часть больше; при равенстве — тому, кто выше в списке
    order = sorted(range(n), key=lambda i: (-(raw[i] - base[i]), i))
    for i in order[:rest]:
        base[i] += 1
    return base


def shares_equal(n: int) -> list[int]:
    """Поровну: 3 оффера -> [34, 33, 33]."""
    return allocate([1.0] * n)


def is_even(shares: Sequence[int]) -> bool:
    """Доли «поровну» (с точностью до округления): 34/33/33, 50/50."""
    return bool(shares) and max(shares) - min(shares) <= 1


def shares_after_add(existing: Sequence[int]) -> list[int]:
    """Доли после добавления оффера (новый в конце).

    * Было поровну: делим поровну на новое число офферов (50/50 -> 34/33/33).
    * Были свои пропорции (например 80/20): новый оффер получает «среднюю» долю,
      остальные уменьшаются пропорционально, так что соотношение между старыми сохраняется.
    """
    if not existing:
        return [TOTAL]
    if is_even(existing):
        return shares_equal(len(existing) + 1)
    mean = sum(existing) / len(existing)
    return allocate([*existing, mean])


def shares_after_remove(existing: Sequence[int], index: int) -> list[int]:
    """Доли оставшихся офферов после удаления оффера с индексом `index`.

    Было поровну: остаётся поровну (34/33/33 -> 50/50). Иначе пропорции оставшихся сохраняются.
    """
    remaining = [s for i, s in enumerate(existing) if i != index]
    if is_even(existing):
        return shares_equal(len(remaining))
    return allocate(remaining)
