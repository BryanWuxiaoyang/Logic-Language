
value
val = value
v = val
val ~ max_val
∀{| val1 | val1 ≤ max_val}
val ~ min_val
∀{| val1 | val1 ≥ min_val}

max
min
size = val

function
func = function
f = func

id = val
i = id
size = val
list = tuple
list
    ::size: list => size
    ::[]: (list, i) => sym
    ::append: (list, sym) => list1
        list1.size = (list.size + 1)
        ∀{| (0 ≤ i) < list.size | list1[i] = list[i]}
        list1[list.size] = sym
    ::push_back = list.append
    ::+: (list, list1) => list2
        list2.size = (list.size + list1.size)
        ∀{| (0 ≤ i) < list.size | list2[i] = list[i]}
        ∀{| (0 ≤ i) < list1.size | list2[list.size + i] = list1[i]}
set ~ list
    : (list, sym) => bool
        bool = ∃{| i | list[i] = sym}
set::lists: set => lists
    lists = {| list | ((list ∀ {| sym ∈ list | sym ∈ set}) ∀ {| sym ∈ set | sym ∈ list}) ∀ {| ((0 ≤ i) < j) < list.size | list[i] ≠ list[j]}}
list::sum: (list, merge_f) => sym
    merge_f: (sym1, sym2) => sym
    ∀
        |- list.size = 0
            sym = null
        |- list.size = 1
            sym = list[0]
        |- list.size > 1
            sym = merge_f(list[0], list[1:].sum(merge_f))
list::sum: list => sym
    sym = list.sum(+)
set::sum: (set, merge_f) => sym
    merge_f: (sym1, sym2) => sym
    syms = {| list ∈ set.lists | sum(list, merge_f)}
    sym = *syms
set::sum: set => sym
    sym = set.sum(+)
list::max: (list, max_f) => sym
    sym = list.sum(max_f)
list::max: list => sym
    sym = list.max(max)
set::max: (set, max_f) => sym
    sym = set.sum(max_f)
set::max: set => sym
    sym = set.max(max)
list::min: (list, min_f) => sym
    sym = list.sum(min_f)
list::min: list => sym
    sym = list.min(min)
set::min: (set, min_f) => sym
    sym = set.sum(min_f)
set::min: set => sym
    sym = set.min(min)
set::argmax: (set, mapping_f, max_f) => sym
    mapping_f: sym => sym1
    max_map_sym = max({| sym ∈ set | mapping_f(sym)}, max_f)
    max_syms = {| mapping_f(sym) = max_map_sym | sym ∈ set}
    sym = *max_syms
set::argmax: (set, mapping_f) => sym
    sym = set.argmax(mapping_f, max)
set::argmin: (set, mapping_f, min_f) => sym
    mapping_f: sym => sym1
    min_map_sym = min({| sym ∈ set | mapping_f(sym)}, min_f)
    min_syms = {| mapping_f(sym) = min_map_sym | sym ∈ set}
    sym = *min_syms
set::argmin: (set, mapping_f) => sym
    sym = set.argmin(mapping_f, min)
