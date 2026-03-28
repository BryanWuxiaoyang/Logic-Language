from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any, Iterable, Optional


class Range(ABC):
    """
    logic: range
      .children / .is_leaf / .intersect / .contains / .intersects / .vals
    """

    @abstractmethod
    def size(self) -> int:
        raise NotImplementedError

    @abstractmethod
    def children(self) -> list["Range"]:
        raise NotImplementedError

    @abstractmethod
    def intersect(self, other: "Range") -> "Range | None":
        raise NotImplementedError

    def is_leaf(self) -> bool:
        return len(self.children()) == 0

    def leafs(self) -> list["Range"]:
        if self.is_leaf():
            return [self]
        out: list["Range"] = []
        for child in self.children():
            out.extend(child.leafs())
        return out

    def contains(self, other: "Range") -> bool:
        inter = self.intersect(other)
        return inter is not None and inter == other

    def intersects(self, other: "Range") -> bool:
        return self.intersect(other) is not None

    def is_inside(self, other: "Range") -> bool:
        return other.contains(self) and self != other


class Modifier(ABC):
    """
    logic: modifier
      .apply(V), .apply_range(range, V), .concat(modifier1)
    """

    @abstractmethod
    def apply(self, value: Any) -> Any:
        raise NotImplementedError

    @abstractmethod
    def apply_range(self, range_obj: Range, value: Any) -> Any:
        raise NotImplementedError

    @abstractmethod
    def concat(self, other: "Modifier") -> "Modifier":
        """
        Concatenate as composition: first `self`, then `other`.
        """
        raise NotImplementedError


class IdentityModifier(Modifier):
    _instance: "IdentityModifier | None" = None

    @classmethod
    def instance(cls) -> "IdentityModifier":
        if cls._instance is None:
            cls._instance = cls()
        return cls._instance

    def apply(self, value: Any) -> Any:
        return value

    def apply_range(self, range_obj: Range, value: Any) -> Any:
        return value

    def concat(self, other: Modifier) -> Modifier:
        return other


class ModifierChain(Modifier):
    def __init__(self, modifiers: Iterable[Modifier]):
        self.modifiers = tuple(modifiers)

    def apply(self, value: Any) -> Any:
        cur = value
        for modifier in self.modifiers:
            cur = modifier.apply(cur)
        return cur

    def apply_range(self, range_obj: Range, value: Any) -> Any:
        cur = value
        for modifier in self.modifiers:
            cur = modifier.apply_range(range_obj, cur)
        return cur

    def concat(self, other: Modifier) -> Modifier:
        if isinstance(other, IdentityModifier):
            return self
        if isinstance(other, ModifierChain):
            return ModifierChain(self.modifiers + other.modifiers)
        return ModifierChain(self.modifiers + (other,))


class SegTreeNode:
    """
    logic: seg_tree node
      fields: range, children, base_val, modifier
      derived: val, push_down, get, set
    """

    def __init__(self, range_obj: Range, merge_fn):
        self.range = range_obj
        self._merge = merge_fn
        self.base_val: Any = None
        self.modifier: Modifier = IdentityModifier.instance()
        self._children: list["SegTreeNode"] | None = None

    def is_leaf(self) -> bool:
        return self.range.is_leaf()

    def val(self) -> Any:
        if self.is_leaf():
            return self.modifier.apply(self.base_val)
        return self.modifier.apply_range(self.range, self.base_val)

    def children(self, identity: Any) -> list["SegTreeNode"]:
        if self._children is None:
            self._children = [
                SegTreeNode(child_range, self._merge)
                for child_range in self.range.children()
            ]
            for child in self._children:
                child.base_val = identity
        return self._children

    def _push_down(self, identity: Any) -> None:
        if isinstance(self.modifier, IdentityModifier):
            return
        if self.is_leaf():
            self.base_val = self.modifier.apply(self.base_val)
            self.modifier = IdentityModifier.instance()
            return

        for child in self.children(identity):
            child.modifier = child.modifier.concat(self.modifier)
        self.base_val = self.modifier.apply_range(self.range, self.base_val)
        self.modifier = IdentityModifier.instance()

    def _merge_values(self, values: Iterable[Any], identity: Any) -> Any:
        out = identity
        for value in values:
            out = self._merge(out, value)
        return out

    def _get(self, query: Range, identity: Any) -> Any:
        # |- range = seg_tree.range
        if query.contains(self.range):
            return self.val()
        # |- range = null
        if not query.intersects(self.range):
            return identity

        # |- range.is_inside(seg_tree.range)
        if self.is_leaf():
            self._push_down(identity)
            return self.val()

        self._push_down(identity)
        return self._merge_values(
            (child._get(query, identity) for child in self.children(identity)),
            identity,
        )

    def _set(self, query: Range, modifier: Modifier, identity: Any) -> None:
        # |- range = seg_tree.range
        if query.contains(self.range):
            self.modifier = self.modifier.concat(modifier)
            return
        # |- range = null
        if not query.intersects(self.range):
            return

        # |- range.is_inside(seg_tree.range)
        if self.is_leaf():
            self.modifier = self.modifier.concat(modifier)
            return

        self._push_down(identity)
        for child in self.children(identity):
            child._set(query, modifier, identity)
        self.base_val = self._merge_values(
            (child.val() for child in self.children(identity)),
            identity,
        )


class SegTree:
    def __init__(self, range_obj: Range, identity: Any):
        self.identity = identity
        self.root = SegTreeNode(range_obj, self.merge)
        self.root.base_val = identity

    def merge(self, left: Any, right: Any) -> Any:
        raise NotImplementedError

    def range_sum(self, range_obj: Range) -> Any:
        return self.root._get(range_obj, self.identity)

    def modify(self, range_obj: Range, modifier: Modifier) -> None:
        self.root._set(range_obj, modifier, self.identity)


class IndexRange(Range):
    """
    Half-open interval [left, right).
    """

    def __init__(self, left: int, right: int):
        if left >= right:
            raise ValueError(f"invalid non-empty range: [{left}, {right})")
        self.left = left
        self.right = right

    def __repr__(self) -> str:
        return f"IndexRange({self.left}, {self.right})"

    def __eq__(self, other: object) -> bool:
        if not isinstance(other, IndexRange):
            return False
        return self.left == other.left and self.right == other.right

    def size(self) -> int:
        return self.right - self.left

    def children(self) -> list[Range]:
        if self.left + 1 == self.right:
            return []
        mid = (self.left + self.right) // 2
        return [IndexRange(self.left, mid), IndexRange(mid, self.right)]

    def contains(self, other: Range) -> bool:
        if not isinstance(other, IndexRange):
            return False
        return self.left <= other.left and other.right <= self.right

    def intersect(self, other: Range) -> Range | None:
        if not isinstance(other, IndexRange):
            return None
        left = max(self.left, other.left)
        right = min(self.right, other.right)
        if left >= right:
            return None
        return IndexRange(left, right)


class AssignAddModifier(Modifier):
    """
    logic: assign_add_modifier
      state: assign_val, add_val
      apply/apply_range/concat as in SegTree.lp @Applications
    """

    def __init__(self, assign_val: Optional[int] = None, add_val: int = 0):
        self.assign_val = assign_val
        self.add_val = add_val

    def apply(self, value: Any) -> Any:
        if self.assign_val is not None:
            return self.assign_val + self.add_val
        if value is None:
            return self.add_val
        return value + self.add_val

    def apply_range(self, range_obj: Range, value: Any) -> Any:
        if self.assign_val is not None:
            return (self.assign_val + self.add_val) * range_obj.size()
        if value is None:
            return self.add_val * range_obj.size()
        return value + self.add_val * range_obj.size()

    def concat(self, other: Modifier) -> Modifier:
        if isinstance(other, IdentityModifier):
            return self
        if isinstance(other, AssignAddModifier):
            if other.assign_val is not None:
                return other
            if self.assign_val is not None:
                return AssignAddModifier(
                    assign_val=self.assign_val,
                    add_val=self.add_val + other.add_val,
                )
            return AssignAddModifier(add_val=self.add_val + other.add_val)
        return ModifierChain([self, other])


class MultModifier(Modifier):
    """
    Non-mergeable modifier used to validate generic ModifierChain behavior.
    """

    def __init__(self, factor: int):
        self.factor = factor

    def apply(self, value: Any) -> Any:
        base = 0 if value is None else value
        return base * self.factor

    def apply_range(self, range_obj: Range, value: Any) -> Any:
        base = 0 if value is None else value
        return base * self.factor

    def concat(self, other: Modifier) -> Modifier:
        if isinstance(other, IdentityModifier):
            return self
        if isinstance(other, MultModifier):
            return MultModifier(self.factor * other.factor)
        return ModifierChain([self, other])


class AddSegTree(SegTree):
    """
    logic: seg_tree::add_seg_tree
      .add(range, V)    = set(range, assign_add_modifier(null, V))
      .assign(range, V) = set(range, assign_add_modifier(V, null))
    """

    def __init__(self, range_obj: tuple[int, int] | IndexRange):
        if isinstance(range_obj, tuple):
            self._full_range = IndexRange(*range_obj)
        else:
            self._full_range = range_obj
        super().__init__(self._full_range, identity=0)

    def merge(self, left: Any, right: Any) -> Any:
        return left + right

    def _validate_tuple_range(self, q_range: tuple[int, int]) -> tuple[int, int]:
        left, right = q_range
        if left > right:
            raise ValueError(f"invalid range: {q_range}")
        if left < self._full_range.left or right > self._full_range.right:
            raise ValueError(
                f"range out of bounds: {q_range}, "
                f"tree range=[{self._full_range.left}, {self._full_range.right})"
            )
        return left, right

    def get(self, q_range: tuple[int, int]) -> int:
        left, right = self._validate_tuple_range(q_range)
        if left == right:
            return 0
        return int(self.range_sum(IndexRange(left, right)))

    def get_one(self, idx: int) -> int:
        return self.get((idx, idx + 1))

    def add(self, q_range: tuple[int, int], value: int) -> None:
        left, right = self._validate_tuple_range(q_range)
        if left == right:
            return
        self.modify(IndexRange(left, right), AssignAddModifier(add_val=value))

    def add_one(self, idx: int, value: int) -> None:
        self.add((idx, idx + 1), value)

    def assign(self, q_range: tuple[int, int], value: int) -> None:
        left, right = self._validate_tuple_range(q_range)
        if left == right:
            return
        self.modify(IndexRange(left, right), AssignAddModifier(assign_val=value))

    def assign_one(self, idx: int, value: int) -> None:
        self.assign((idx, idx + 1), value)

    def mult(self, q_range: tuple[int, int], factor: int) -> None:
        """
        Not from SegTree.lp applications, added only for chain-composition checks.
        """
        left, right = self._validate_tuple_range(q_range)
        if left == right:
            return
        self.modify(IndexRange(left, right), MultModifier(factor))

    def mult_one(self, idx: int, factor: int) -> None:
        self.mult((idx, idx + 1), factor)


if __name__ == "__main__":
    import random

    def _verify_all_ranges(tree: AddSegTree, arr: list[int], tag: str) -> None:
        n = len(arr)
        for left in range(n + 1):
            for right in range(left, n + 1):
                got = tree.get((left, right))
                want = sum(arr[left:right])
                if got != want:
                    raise AssertionError(
                        f"{tag}: query=({left},{right}) got={got} want={want} arr={arr}"
                    )

    def _check_invalid_ranges() -> None:
        tree = AddSegTree((0, 4))
        invalid = [(-1, 1), (0, 5), (3, 2)]
        for q_range in invalid:
            for op in (
                lambda: tree.get(q_range),
                lambda: tree.add(q_range, 1),
                lambda: tree.assign(q_range, 1),
                lambda: tree.mult(q_range, 2),
            ):
                try:
                    op()
                    raise AssertionError(f"expected ValueError for range {q_range}")
                except ValueError:
                    pass

    def _check_modifier_chain() -> None:
        tree = AddSegTree((0, 8))
        tree.assign((0, 8), 1)
        tree.mult((0, 8), 3)
        tree.add((0, 8), 2)
        _ = tree.get((0, 4))  # force push-down on a branch
        tree.add((0, 4), 10)

        left = tree.get((0, 4))
        right = tree.get((4, 8))
        total = tree.get((0, 8))
        if left != 60 or right != 20 or total != 80:
            raise AssertionError(
                f"modifier chain mismatch: left={left} right={right} total={total}"
            )

    # Deterministic scenario.
    n = 8
    seg = AddSegTree((0, n))
    arr = [0] * n
    _verify_all_ranges(seg, arr, "init")

    ops: list[tuple[str, tuple[int, int], int]] = [
        ("add", (0, 8), 1),
        ("mult", (0, 8), 2),
        ("add", (2, 5), 3),
        ("assign", (4, 7), 10),
        ("mult", (4, 8), -1),
        ("add", (3, 4), -4),
        ("assign", (0, 1), -7),
        ("mult", (1, 7), 3),
        ("add", (1, 7), 2),
        ("assign", (6, 8), 5),
        ("mult", (0, 0), 999),   # empty range no-op
        ("add", (3, 3), 999),    # empty range no-op
        ("assign", (2, 2), 123), # empty range no-op
    ]

    for step, (op, q_range, value) in enumerate(ops, start=1):
        left, right = q_range
        if op == "add":
            seg.add(q_range, value)
            for i in range(left, right):
                arr[i] += value
        elif op == "assign":
            seg.assign(q_range, value)
            for i in range(left, right):
                arr[i] = value
        elif op == "mult":
            seg.mult(q_range, value)
            for i in range(left, right):
                arr[i] *= value
        else:
            raise AssertionError(f"unknown op: {op}")
        _verify_all_ranges(seg, arr, f"deterministic-{step}")

    _check_modifier_chain()

    # Random differential checks.
    for seed in range(40):
        rng = random.Random(seed)
        n = rng.randint(1, 32)
        seg = AddSegTree((0, n))
        arr = [0] * n
        for step in range(300):
            left = rng.randrange(0, n + 1)
            right = rng.randrange(left, n + 1)
            q_range = (left, right)
            choice = rng.random()
            if choice < 0.4:
                delta = rng.randint(-20, 20)
                seg.add(q_range, delta)
                for i in range(left, right):
                    arr[i] += delta
            elif choice < 0.7:
                value = rng.randint(-20, 20)
                seg.assign(q_range, value)
                for i in range(left, right):
                    arr[i] = value
            elif choice < 0.9:
                factor = rng.randint(-4, 4)
                seg.mult(q_range, factor)
                for i in range(left, right):
                    arr[i] *= factor
            else:
                got = seg.get(q_range)
                want = sum(arr[left:right])
                if got != want:
                    raise AssertionError(
                        f"random seed={seed} step={step}: "
                        f"query={q_range} got={got} want={want} arr={arr}"
                    )
        _verify_all_ranges(seg, arr, f"random-final-{seed}")

    _check_invalid_ranges()
    print("All checks passed.")
