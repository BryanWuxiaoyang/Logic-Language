
~

∀
    | ^sym
    ^sym ~ ^sym

∀
    | ^sym1, ^sym2, ^sym3
    | ^sym1 ~ ^sym2
    | ^sym2 ~ ^sym3
    ^sym1 ~ ^sym3
    
Symbol
∀{| ^sym | Symbol ~ ^sym}

Sym
Sym = Symbol

Bool
true
Bool ~ true
false
Bool ~ false

Function
Func
Func = Function
F
F = Func

Predicate
Function ~ Predicate
Pred
Pred = Predicate

Predicate ~ Set
Set
Value

Tuple
Set ~ Tuple

Char
String
Str
Str = String
Tuple ~ String
∀
    | _string
    | String ~ _string
    | _char ∈ _string
    Char ~ _char

Val
Val = Value

max: (_val1, _val2) => _val
max: _vals => _val
min: (_val1, _val2) => _val
min: _vals => _val

Size
Size = Val

Cnt
Cnt = Val

Num
Num = Val

Id
Id = Val

List
    ::size: _list => _size_val
    ::[]: (_list, _id) => _sym
    ::+: (_list, _list1) => _list2
        _list2.size = (_list.size + _list1.size)
        ∀{| _id | 0 ≤ _id < _list.size | _list2[_id] = _list[_id]}
        ∀{| _id | 0 ≤ _id < _list1.size | _list2[_list.size + _id] = _list1[_id]}
List = Tuple

[:]: (_val1, _val2) => _list
    | _val
    | _val1 <= _val
    | _val < _val2
    _list.size = _val2 - _val1
    _list[_val - _val1] = _val

[:]: (_list, _val1, _val2) => _list1
    | _val
    | _val1 <= _val
    | _val < _val2
    _list1.size = _val2 - _val1
    _list1[_val - _val1] = _list[_val]

List
    ::∈: (_sym, _list) => _bool
        _bool = ∃{| _id | _list[_id] = _sym}
Set ~ List
Set::lists: _set => _lists
    _lists = {
        | _list1
        ∀{
            | _sym ∈ _list1
            _sym ∈ _set
        }
        ∀{
            | _sym ∈ _set
            _sym ∈ _list1
        }
        ∀{
            | _id1, _id2
            | 0 ≤ _id1 < _id2
            | _id2 < _list1.size
            _list1[_id1] ≠ _list1[_id2]
        }
    }
List::sum: (_list, _merge_f) => _sum_sym
    | _merge_f: (_sym1, _sym2) => _merge_sym
    ∀
        |- _list.size = 0
            _sum_sym = null
        |- _list.size = 1
            _sum_sym = _list[0]
        |- _list.size > 1
            _sum_sym = _merge_f(_list[0], _list[1: _list.size].sum(_merge_f))
List::sum: _list => _sum_sym
    _sum_sym = _list.sum(+)
Set::sum: (_set, _merge_f) => _set_sum_sym
    | _merge_f: (_sym1, _sym2) => _merge_sym
    | _syms = {| _list1 ∈ _set.lists => sum(_list1, _merge_f)}
    _set_sum_sym = *_syms
Set::sum: _set => _set_sum_sym
    _set_sum_sym = _set.sum(+)
List::max: (_list, _max_f) => _max_sym
    _max_sym = _list.sum(_max_f)
List::max: _list => _max_sym
    _max_sym = _list.max(max)
Set::max: (_set, _max_f) => _max_sym
    _max_sym = _set.sum(_max_f)
Set::max: _set => _max_sym
    _max_sym = _set.max(max)
List::min: (_list, _min_f) => _min_sym
    _min_sym = _list.sum(_min_f)
List::min: _list => _min_sym
    _min_sym = _list.min(min)
Set::min: (_set, _min_f) => _min_sym
    _min_sym = _set.sum(_min_f)
Set::min: _set => _min_sym
    _min_sym = _set.min(min)
Set::argmax: (_set, _mapping_f, _max_f) => _argmax_sym
    | _mapping_f: _sym => _sym1
    | _max_map_sym = max({| _sym ∈ _set => _mapping_f(_sym)}, _max_f)
    | _max_syms = {| _sym | _sym ∈ _set, _mapping_f(_sym) = _max_map_sym}
    _argmax_sym = *_max_syms
Set::argmax: (_set, _mapping_f) => _argmax_sym
    _argmax_sym = _set.argmax(_mapping_f, max)
Set::argmin: (_set, _mapping_f, _min_f) => _argmin_sym
    | _mapping_f: _sym => _sym1
    | _min_map_sym = min({| _sym ∈ _set => _mapping_f(_sym)}, _min_f)
    | _min_syms = {| _sym | _sym ∈ _set, _mapping_f(_sym) = _min_map_sym}
    _argmin_sym = *_min_syms
Set::argmin: (_set, _mapping_f) => _argmin_sym
    _argmin_sym = _set.argmin(_mapping_f, min)
