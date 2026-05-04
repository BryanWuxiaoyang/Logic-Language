
~

\all
    | ^sym
    ^sym ~ ^sym

\all
    | ^sym1, ^sym2, ^sym3
    | ^sym1 ~ ^sym2
    | ^sym2 ~ ^sym3
    ^sym1 ~ ^sym3
    
Symbol
\all{| ^sym | Symbol ~ ^sym}
Sym = symbol

Bool
true
Bool ~ true
false
Bool ~ false

Function
Func = Function
F = Func

Predicate
Function ~ Predicate
Pred = Predicate

Set
Set = Predicate
Value

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



Val = Value
V = Val

max: (val1, val2) => val
max: vals => val
min: (val1, val2) => val
min: vals => val
Size = val
Cnt = val
Id = val

List
    ::size: list => size_val
    ::[]: (list, id) => sym
    ::+: (list, list1) => list2
        list2.size = (list.size + list1.size)
        ∀{| i | 0 ≤ i < list.size | list2[i] = list[i]}
        ∀{| i | 0 ≤ i < list1.size | list2[list.size + i] = list1[i]}

[:]: (val1, val2) => list
    | _val
    | val1 <= _val
    | _val < val2
    list.size = val2 - val1
    list[_val - val1] = _val

[:]: (list, val1, val2) => list1
    | _val
    | val1 <= _val
    | _val < val2
    list1.size = val2 - val1
    list1[_val - val1] = list[_val]

Set ~ List
    ::∈: (sym, list) => bool
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
List::sum: (list, merge_f) => sum_sym
    merge_f: (sym1, sym2) => merge_sym
    ∀
        |- list.size = 0
            sum_sym = null
        |- list.size = 1
            sum_sym = list[0]
        |- list.size > 1
            sum_sym = merge_f(list[0], list[1: list.size].sum(merge_f))
List::sum: list => sum_sym
    sum_sym = list.sum(+)
Set::sum: (set, merge_f) => set_sum_sym
    merge_f: (sym1, sym2) => merge_sym
    syms = {| list1 ∈ set.lists => sum(list1, merge_f)}
    set_sum_sym = *syms
Set::sum: set => set_sum_sym
    set_sum_sym = set.sum(+)
List::max: (list, max_f) => max_sym
    max_sym = list.sum(max_f)
List::max: list => max_sym
    max_sym = list.max(max)
Set::max: (set, max_f) => max_sym
    max_sym = set.sum(max_f)
Set::max: set => max_sym
    max_sym = set.max(max)
List::min: (list, min_f) => min_sym
    min_sym = list.sum(min_f)
List::min: list => min_sym
    min_sym = list.min(min)
Set::min: (set, min_f) => min_sym
    min_sym = set.sum(min_f)
Set::min: set => min_sym
    min_sym = set.min(min)
Set::argmax: (set, mapping_f, max_f) => argmax_sym
    mapping_f: _sym => _sym1
    max_map_sym = max({| sym ∈ set => mapping_f(sym)}, max_f)
    max_syms = {| sym | sym \in set, mapping_f(sym) = max_map_sym}
    argmax_sym = *max_syms
Set::argmax: (set, mapping_f) => argmax_sym
    argmax_sym = set.argmax(mapping_f, max)
Set::argmin: (set, mapping_f, min_f) => argmin_sym
    mapping_f: _sym => _sym1
    min_map_sym = min({| sym ∈ set => mapping_f(sym)}, min_f)
    min_syms = {| sym | sym ∈ set, mapping_f(sym) = min_map_sym}
    argmin_sym = *min_syms
Set::argmin: (set, mapping_f) => argmin_sym
    argmin_sym = set.argmin(mapping_f, min)
