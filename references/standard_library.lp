null
true
∀{| sym | true(sym) = true}
false
∀{| sym | false(sym) = false}
bool
bool ~ true
bool ~ false
!
!(false) = true
!(true) = false
~
# intrinsic operators on symbols and values
=: (symbol1, symbol2) => bool
    ∀
        |- symbol1 = null
            bool = false
        |- symbol2 = null
            bool = false
        |- else
            condition("symbol1 and symbol2 have same behavior")

≠ = !=

==: (symbol1, symbol2) => bool
    condition("for structural compare, not just pure symbol identity")

&&
&&(true, true) :=: true
&&(false, true) :=: false
&&(true, false) :=: false
&&(false, false) :=: false
∧ = &&
||
||(true, true) :=: true
||(false, true) :=: true
||(true, false) :=: true
||(false, false) :=: false
∨ = ||
tuple
    ::size
set
    : symbol => bool
    ::size: set => size
    ::⊆: (set, set1) => bool
        bool = ∀{| symbol ∈ set | symbol ∈ set1}
    ::⊂: (set, set1) => bool
        bool = ((set ⊆ set1) && (set ≠ set1))
full_set
{*} = full_set
empty_set
{} = empty_set
value
val = value
v = val
set ~ value
∀{| sym | value(sym) = (sym = value)}
val ~ max_val
∀{| val | val ≤ max_val}
val ~ min_val
∀{| val | val ≥ min_val}
>
≥(\ge) = (> || =)
<
≤(\le) = (< || =)
*
/
+
-
max
min
val = size
∈: (symbol, set) => bool
    bool = set(symbol)
∉: (symbol, set) => bool
    bool = !set(symbol)
⊆: (set, set1) => bool
    bool = ∀{| symbol ∈ set | symbol ∈ set1}
⊂: (set, set1) => bool
    bool = ((set ⊆ set1) && (set ≠ set1))
=: (set1, set2) => bool
    bool = ((set1 ⊆ set2) && (set2 ⊆ set1))
condition: (symbols, desc) => bool
condition: desc => bool
∀: set => bool
∃: set => bool
set.is_singleton: set => bool
    bool = ∀{set.size = 1}
*: set => symbol
    | set.is_singleton
    condition("extract the single element from set")
    ∀{| symbol1 ∈ set | symbol = symbol1}
map
    ::keys
    ::vals
    ::items(kv_pairs): function => key_val_set
    ::__call__: (map, key) => val
৹
∀{| f1, f2, sym | ৹(f1, f2)(sym) = f2(f1(sym))}
identity_f
∀{| sym | identity_f(sym) = sym}
^: (f, n) => f1
    | val ~ n
    ∀
        |- n = 0
            f1 = identity_f
        |- n > 0
            f1 = ৹(f, ^(f, n - 1))
i
value = i
id
value = id
size
value = size
list
    ::size: list => size
    ::[]: (list, i) => symbol
    ::append: (list, symbol) => list1
        list1.size = (list.size + 1)
        ∀{| (0 ≤ i) < list.size | list1[i] = list[i]}
        list1[list.size] = symbol
    ::push_back = list.append
    ::concat(+): (list, list1) => list2
        list2.size = (list.size + list1.size)
        ∀{| (0 ≤ i) < list.size | list2[i] = list[i]}
        ∀{| (0 ≤ i) < list1.size | list2[list.size + i] = list1[i]}
set ~ list
    : (list, symbol) => bool
        bool = ∃{| i | list[i] = symbol}
set :: lists: set => lists
    lists = {| list | ((list ∀ {| symbol ∈ list | symbol ∈ set}) ∀ {| symbol ∈ set | symbol ∈ list}) ∀ {| ((0 ≤ i) < j) < list.size | list[i] ≠ list[j]}}
slice
    ::from_id
    ::to_id
    ∀{| slice.to_id ≥ 0 | slice.from_id ≤ slice.to_id}
    ::__init__([:]): (from_id, to_id) => slice
        slice.from_id = from_id
        slice.to_id = to_id
    ::__init__([: -]): from_id => slice
        slice.from_id = from_id
        slice.to_id = max_val
    ::__init__([-:]): to_id => slice
        slice.from_id = min_val
        slice.to_id = to_id
∀
    | slice
    | slice.from_id ≠ min_val
    | slice.to_id ≠ max_val
    | slice.to_id ≥ 0
    list ~ slice
    slice.size = (slice.to_id - slice.from_id)
    ∀{| (0 ≤ i) < slice.size | slice[i] = (slice.from_id + i)}
# list[i:j]
list :: slice: (list, slice) => list1
    from_id = max(slice.from_id, 0)
    ∀
        |- slice.to_id < 0
            # list[:-1] = list[:list.size - 1]
            to_id = (list.size + slice.to_id)
        |- slice.to_id ≥ 0
            to_id = min(list.size, slice.to_id)
    ∀
        |- from_id < to_id
            list1.size = (to_id - from_id)
        |- from_id ≥ to_id
            list1.size = 0
    ∀{| (0 ≤ i) < list1.size | list1[i] = list[from_id + i]}
list :: sum: (list, merge_f) => symbol
    merge_f: (symbol1, symbol2) => symbol
    ∀
        |- list.size = 0
            symbol = null
        |- list.size = 1
            symbol = list[0]
        |- list.size > 1
            symbol = merge_f(list[0], list[1:].sum(merge_f))
list :: sum: list => symbol
    symbol = list.sum(+)
set :: sum: (set, merge_f) => symbol
    merge_f: (symbol1, symbol2) => symbol
    symbols = {| list ∈ set.lists | sum(list, merge_f)}
    symbol = *symbols
set :: sum: set => symbol
    symbol = set.sum(+)
list :: max: (list, max_f) => symbol
    symbol = list.sum(max_f)
list :: max: list => symbol
    symbol = list.max(max)
set :: max: (set, max_f) => symbol
    symbol = set.sum(max_f)
set :: max: set => symbol
    symbol = set.max(max)
list :: min: (list, min_f) => symbol
    symbol = list.sum(min_f)
list :: min: list => symbol
    symbol = list.min(min)
set :: min: (set, min_f) => symbol
    symbol = set.sum(min_f)
set :: min: set => symbol
    symbol = set.min(min)
set :: argmax: (set, mapping_f, max_f) => symbol
    mapping_f: symbol => symbol1
    max_map_symbol = max({| sym ∈ set | mapping_f(sym)}, max_f)
    max_syms = {| mapping_f(sym) = max_map_symbol | sym ∈ set}
    symbol = *max_syms
set :: argmax: (set, mapping_f) => symbol
    symbol = set.argmax(mapping_f, max)
set :: argmin: (set, mapping_f, min_f) => symbol
    mapping_f: symbol => symbol1
    min_map_symbol = min({| sym ∈ set | mapping_f(sym)}, min_f)
    min_syms = {| mapping_f(sym) = min_map_symbol | sym ∈ set}
    symbol = *min_syms
set :: argmin: (set, mapping_f) => symbol
    symbol = set.argmin(mapping_f, min)
