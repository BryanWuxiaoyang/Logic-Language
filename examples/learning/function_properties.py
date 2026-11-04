"""Finite integer examples; these checks are not proofs over infinite sets."""


def is_mapping(function, domain, codomain):
    return {function(value) for value in domain} <= set(codomain)


def is_injective(function, domain):
    values = set(domain)
    return len({function(value) for value in values}) == len(values)


def is_surjective(function, domain, codomain):
    return set(codomain) <= {function(value) for value in domain}


if __name__ == "__main__":
    square = lambda value: value * value
    integers = set(range(-2, 3))
    nonnegative = {0, 1, 2}
    image = {square(value) for value in nonnegative}
    print(is_injective(square, integers))
    print(is_injective(square, nonnegative))
    print(is_surjective(square, nonnegative, {0, 1, 2, 3, 4}))
    print(is_surjective(square, nonnegative, image))
