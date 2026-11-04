"""Integer implementation of the constraints in quadruple.lp."""


def quadruple(value):
    return value * 4


if __name__ == "__main__":
    print([quadruple(value) for value in (-2, 0, 3)])
