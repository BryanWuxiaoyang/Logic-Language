"""Check example LP and compare representative programs with their contracts.

Run from any directory: python examples/check_examples.py
"""

from importlib.util import module_from_spec, spec_from_file_location
from itertools import combinations
from pathlib import Path
import sys

EXAMPLES = Path(__file__).resolve().parent
PROJECT = EXAMPLES.parent
sys.path.insert(0, str(PROJECT / "scripts"))

from module_check import check_module


def load_example(relative_path):
    path = EXAMPLES / relative_path
    spec = spec_from_file_location(path.stem, path)
    module = module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def require(condition, message):
    if not condition:
        raise AssertionError(message)


def main():
    paths = sorted(EXAMPLES.rglob("*.lp"))
    for path in paths:
        result = check_module(path.read_text(encoding="utf-8"), str(path), path.parent, is_file=True)
        require(result["summary"] == {"error_count": 0, "warning_count": 0}, str(result))

    quadruple = load_example("contracts/quadruple.py").quadruple
    for value in range(-12, 13):
        twice = value + value
        require(quadruple(value) == twice + twice, "computation dependency")
        require(quadruple(value) >= 0 if value >= 0 else quadruple(value) < 0, "sign guarantee")
        for other in range(-12, value + 1):
            require(quadruple(other) <= quadruple(value), "order preservation")

    minimum = load_example("algorithms/minimum.py").minimum
    for count in range(1, 6):
        for values in combinations(range(-2, 3), count):
            result = minimum(set(values))
            require(result in values and all(result <= value for value in values), "minimum contract")
    try:
        minimum(set())
    except ValueError:
        pass
    else:
        raise AssertionError("chosen empty-input handling")

    eligible_ids = load_example("data_processing/eligible_ids.py").eligible_ids
    require(eligible_ids([]) == set(), "empty input")
    users = [
        {"id": 1, "active": True, "age": 18},
        {"id": 1, "active": True, "age": 22},
        {"id": 2, "active": True, "age": 17},
        {"id": 3, "active": False, "age": 40},
    ]
    require(eligible_ids(users) == {1}, "age boundary, activity, and duplicate IDs")
    for count in range(len(users) + 1):
        for records in combinations(users, count):
            output = eligible_ids(records)
            for candidate in {1, 2, 3, 99}:
                witness = any(u["id"] == candidate and u["active"] and u["age"] >= 18 for u in records)
                require((candidate in output) == witness, "image-set membership equivalence")

    can_read = load_example("access_control/can_read.py").can_read
    for owns in (False, True):
        for shares in (False, True):
            doc = {"owner": "alice" if owns else "bob", "shared": {"alice"} if shares else set()}
            require(can_read("alice", doc) == (owns or shares), "access truth table")

    Point = load_example("classes/point.py").Point
    for x_value in (-3, 0, 7):
        point = Point(x_value, 4)
        for delta in (-2, 0, 4):
            require(point.shifted_x(delta) == point.x_value + delta, "method receiver and field relationship")
            require((point.x_value, point.y_value) == (x_value, 4), "returned coordinate preserves source point")

    properties = load_example("learning/function_properties.py")
    square = lambda value: value * value
    domain = {0, 1, 2}
    image = {square(value) for value in domain}
    require(not properties.is_injective(square, set(range(-2, 3))), "injectivity counterexample")
    require(properties.is_injective(square, domain), "restricted finite domain")
    require(not properties.is_surjective(square, domain, {0, 1, 2, 3, 4}), "missing preimage")
    require(properties.is_mapping(square, domain, image) and properties.is_surjective(square, domain, image), "image codomain")
    require(properties.is_injective(square, set()), "empty-domain injectivity")
    require(properties.is_surjective(square, set(), set()), "empty-codomain surjectivity")
    print(f"Checked {len(paths)} LP files: 0 errors, 0 warnings.")
    print("Program correspondence checks passed (finite cases, not a formal proof).")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
