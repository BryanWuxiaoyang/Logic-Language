"""Integer-set implementation; empty input is outside the LP contract."""


def minimum(values):
    if not values:
        raise ValueError("nonempty set required")
    iterator = iter(values)
    best = next(iterator)
    for value in iterator:
        if value < best:
            best = value
    return best


if __name__ == "__main__":
    print(minimum({-2, 0, 3}))
