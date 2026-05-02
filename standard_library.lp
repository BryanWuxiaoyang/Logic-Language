symbol
sym = symbol
value
set
tuple
set~tuple
list = tuple
char
string
str = string
bool
true
false
function
func = function
f = func

val = value
v = val
val ~ max_val
∀{| val1 | val1 ≤ max_val}
val ~ min_val
∀{| val1 | val1 ≥ min_val}

max: (val1, val2) => val
max: vals => val
min: (val1, val2) => val
min: vals => val
size = val
cnt = val
id = val
size = val
list
    ::size: list => size
    ::[]: (list, id) => sym
    ::+: (list, list1) => list2
        list2.size = (list.size + list1.size)
        ∀{| i | 0 ≤ i < list.size | list2[i] = list[i]}
        ∀{| i | 0 ≤ i < list1.size | list2[list.size + i] = list1[i]}
set ~ list
    : (list, sym) => bool
        bool = ∃{| i | list[i] = sym}
set::lists: set => lists
    lists = {
        | list1
        ∀{
            | sym ∈ list1
            sym ∈ set
        }
        ∀{
            | sym ∈ set
            sym ∈ list1
        }
        ∀{
            | i, j
            | 0 ≤ i
            | i < j
            | j < list1.size
            list1[i] ≠ list1[j]
        }
    }
list::sum: (list, merge_f) => sym
    merge_f: (sym1, sym2) => sym
    ∀
        |- list.size = 0
            sym = null
        |- list.size = 1
            sym = list[0]
        |- list.size > 1
            sym = merge_f(list[0], list[1: list.size].sum(merge_f))
list::sum: list => sym
    sym = list.sum(+)
set::sum: (set, merge_f) => sym
    merge_f: (sym1, sym2) => sym
    syms = {| list1 ∈ set.lists => sum(list1, merge_f)}
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
    max_map_sym = max({| sym ∈ set => mapping_f(sym)}, max_f)
    max_syms = {| sym | sym \in set, mapping_f(sym) = max_map_sym}
    sym = *max_syms
set::argmax: (set, mapping_f) => sym
    sym = set.argmax(mapping_f, max)
set::argmin: (set, mapping_f, min_f) => sym
    mapping_f: sym => sym1
    min_map_sym = min({| sym ∈ set => mapping_f(sym)}, min_f)
    min_syms = {| sym | sym ∈ set, mapping_f(sym) = min_map_sym}
    sym = *min_syms
set::argmin: (set, mapping_f) => sym
    sym = set.argmin(mapping_f, min)
