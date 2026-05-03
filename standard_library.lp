
~

\all
    | __sym
    __sym ~ __sym

\all
    | __sym1, __sym2, __sym3
    | __sym1 ~ __sym2
    | __sym2 ~ __sym3
    __sym1 ~ __sym3
    
Symbol
\all{| __sym | Symbol ~ __sym}
Sym = symbol
Value
Set
Tuple
Set ~ Tuple
List = Tuple
Char
String
Str = String
Tuple ~ String
\all
    | _string
    | String ~ _string
    | _char \in _string
    Char ~ _char
Bool
true
Bool ~ true
false
Bool ~ false
Function
Func = Function
F = Func


Val = Value
V = Val

max: (val1, val2) => val
max: vals => val
min: (val1, val2) => val
min: vals => val
Size = val
Cnt = val
Id = val
list
    ::size: list => size
    ::[]: (list, id) => sym
    ::+: (list, list1) => list2
        list2.size = (list.size + list1.size)
        ∀{| i | 0 ≤ i < list.size | list2[i] = list[i]}
        ∀{| i | 0 ≤ i < list1.size | list2[list.size + i] = list1[i]}
Set ~ List
    : (list, sym) => bool
        bool = ∃{| i | list[i] = sym}
Set::lists: set => lists
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
List::sum: (list, merge_f) => sym
    merge_f: (sym1, sym2) => sym
    ∀
        |- list.size = 0
            sym = null
        |- list.size = 1
            sym = list[0]
        |- list.size > 1
            sym = merge_f(list[0], list[1: list.size].sum(merge_f))
List::sum: list => sym
    sym = list.sum(+)
Set::sum: (set, merge_f) => sym
    merge_f: (sym1, sym2) => sym
    syms = {| list1 ∈ set.lists => sum(list1, merge_f)}
    sym = *syms
Set::sum: set => sym
    sym = set.sum(+)
List::max: (list, max_f) => sym
    sym = list.sum(max_f)
List::max: list => sym
    sym = list.max(max)
Set::max: (set, max_f) => sym
    sym = set.sum(max_f)
Set::max: set => sym
    sym = set.max(max)
List::min: (list, min_f) => sym
    sym = list.sum(min_f)
List::min: list => sym
    sym = list.min(min)
Set::min: (set, min_f) => sym
    sym = set.sum(min_f)
Set::min: set => sym
    sym = set.min(min)
Set::argmax: (set, mapping_f, max_f) => sym
    mapping_f: sym => sym1
    max_map_sym = max({| sym ∈ set => mapping_f(sym)}, max_f)
    max_syms = {| sym | sym \in set, mapping_f(sym) = max_map_sym}
    sym = *max_syms
Set::argmax: (set, mapping_f) => sym
    sym = set.argmax(mapping_f, max)
Set::argmin: (set, mapping_f, min_f) => sym
    mapping_f: sym => sym1
    min_map_sym = min({| sym ∈ set => mapping_f(sym)}, min_f)
    min_syms = {| sym | sym ∈ set, mapping_f(sym) = min_map_sym}
    sym = *min_syms
Set::argmin: (set, mapping_f) => sym
    sym = set.argmin(mapping_f, min)
