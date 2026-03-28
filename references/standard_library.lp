null

bool
bool~true
bool~false

!: bool => bool1
    ∀
        |- bool = true
            bool1 = false
        |- bool = false
            bool1 = true

~: (symbol1, symbol2) => bool

# intrinsic operators on symbols and values
=: (symbol1, symbol2) => bool
    ∀
        |- symbol1 = null
            bool = false
        |- symbol2 = null
            bool = false
        |- else
            bool = condition("symbol1 and symbol2 satisfy same conditions")

>: (symbol1, symbol2) => bool
≥(\ge): (symbol1, symbol2) => bool
<: (symbol1, symbol2) => bool
≤(\le): (symbol1, symbol2) => bool
≠: (symbol1, symbol2) => bool
*: (symbol1, symbol2) => symbol
/: (symbol1, symbol2) => symbol
+: (symbol1, symbol2) => symbol
-: (symbol1, symbol2) => symbol
max: (symbol1, symbol2) => symbol
min: (symbol1, symbol2) => symbol

value(val)(v)

val~max_val
∀{ val ≤ max_val | val }

val~min_val
∀{ val ≥ min_val | val }

val~size~val

tuple
    ::size

set
    : symbol => bool
    ::size: set => size
    ::⊆(\included_in): (set, set1) => bool
        bool = ∀{ symbol ∈ set1 | symbol ∈ set }
    ::⊂(\subset): (set, set1) => bool
        bool = ∀{ set ⊆ set1, set ≠ set1 }

∈(\in): (symbol, set) => bool
    bool = set(symbol)

∉(\notin): (symbol, set) => bool
    bool = !set(symbol)

condition: (symbols, desc) => bool
condition: desc => bool

∀: set => bool
∃: set => bool

set.is_singleton: set => bool
    bool = ∀{ set.size = 1 }

*: set => symbol
    | set.is_singleton
    condition("extract the single element from set")
    ∀{ symbol = symbol1 | symbol1 ∈ set }


function
    ::in_args_size
    ::out_args_size
    ::arity = (in_args_size, out_args_size)
    ::name
    ::signature: function => signature
        ∀
            |- function.name ≠ null
                signature = (function.name, function.in_args_size, function.out_args_size)
            |- function.name = null
                signature = null
                # signature will not equal if it is null

∀{ function1 = function2
    | function1.signature = function2.signature
    | function1, function2
}

function
    ::keys
    ::vals
    ::items(kv_pairs): function => key_val_set

identity_function: args_size => f
    f.in_args_size = args_size
    f.out_args_size = args_size
    f = in_args -> in_args

function
    ::is_endo: function => bool
        bool = ∀{ function.in_args_size = function.out_args_size }
    
    ::args_size: function => size
        | function.is_endo
        size = function.in_args_size

    ::concat(\concat): (function, function1) => function2
    ::concat(৹): (function, function1) => function2
        | function.is_endo
        | function1.is_endo
        | function.args_size = function1.args_size
        function2.is_endo
        function2.args_size = function.args_size
        ∀{ function2(*in_args) = function1(*function(*in_args)) | in_args }

    ::exp(^): (function, v) => function1
        ∀
            |- v = 0
                function1 = identity_function(function.in_args_size)
            |- v > 0
                function1 = function ৹ function^(v-1)

value~i~value
value~id~value
value~n~value
value~size~value

list
    ::size: list => size
    ::get([]): (list, i) => symbol
      
    ::append(push_back): (list, symbol) => list1
        list1.size = list.size + 1
        ∀{ list1[i] = list[i] | 0 ≤ i < list.size }
        list1[list.size] = symbol

    ::concat(+): (list, list1) => list2
        list2.size = list.size + list1.size
        ∀{ list2[i] = list[i] | 0 ≤ i < list.size }
        ∀{ list2[list.size + i] = list1[i] | 0 ≤ i < list1.size }

set~list
    : (list, symbol) => bool
        bool = ∃{ list[i] = symbol | i }

set::lists: set => lists
    lists = { list
        ∀{ symbol ∈ set | symbol ∈ list }
        ∀{ symbol ∈ list | symbol ∈ set }
        ∀{ list[i] ≠ list[j] | 0 ≤ i < j < list.size }
        | list
    }

slice
    ::from_id
    ::to_id
    ∀{ slice.from_id ≤ slice.to_id
        | slice.to_id ≥ 0
    }

    ::__init__([:]): (from_id, to_id) => slice
        slice.from_id = from_id
        slice.to_id = to_id
    
    ::__init__([:-]): from_id => slice
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
    list~slice
    slice::size = slice.to_id - slice.from_id
    ∀{ slice[i] = slice.from_id + i | 0 ≤ i < slice.size }

# list[i:j]
list::slice: (list, slice) => list1
    from_id = max(slice.from_id, 0)
    ∀
        |- slice.to_id < 0
            # list[:-1] = list[:list.size - 1]
            to_id = list.size + slice.to_id
        |- slice.to_id ≥ 0
            to_id = min(list.size, slice.to_id)
    
    ∀
        |- from_id < to_id
            list1.size = to_id - from_id
        |- from_id ≥ to_id
            list1.size = 0
    ∀{ list1[i] = list[from_id + i] | 0 ≤ i < list1.size }


list::sum: (list, merge_f) => symbol
    merge_f: (symbol1, symbol2) => symbol
    ∀
        |- list.size = 0
            symbol = null
        |- list.size = 1
            symbol = list[0]
        |- list.size > 1
            symbol = merge_f(list[0], list[1:].sum(merge_f))

list::sum: list => symbol
    symbol = list.sum(+)

set::sum: (set, merge_f) => symbol
    merge_f: (symbol1, symbol2) => symbol
    symbols = { sum(list, merge_f) | list ∈ set.lists }
    symbol = *symbols

set::sum: set => symbol
    symbol = set.sum(+)

list::max: (list, max_f) => symbol
    symbol = list.sum(max_f)

list::max: list => symbol
    symbol = list.max(max)

set::max: (set, max_f) => symbol
    symbol = set.sum(max_f)

set::max: set => symbol
    symbol = set.max(max)

list::min: (list, min_f) => symbol
    symbol = list.sum(min_f)

list::min: list => symbol
    symbol = list.min(min)

set::min: (set, min_f) => symbol
    symbol = set.sum(min_f)

set::min: set => symbol
    symbol = set.min(min)

set::argmax: (set, mapping_f, max_f) => symbol
    mapping_f: symbol => symbol1
    max_map_symbol = max({ mapping_f(sym) | sym ∈ set }, max_f)
    max_syms = { | mapping_f(sym) = max_map_symbol | sym ∈ set }
    symbol = *max_syms

set::argmax: (set, mapping_f) => symbol
    symbol = set.argmax(mapping_f, max)

set::argmin: (set, mapping_f, min_f) => symbol
    mapping_f: symbol => symbol1
    min_map_symbol = min({ mapping_f(sym) | sym ∈ set }, min_f)
    min_syms = { | mapping_f(sym) = min_map_symbol | sym ∈ set }
    symbol = *min_syms

set::argmin: (set, mapping_f) => symbol
    symbol = set.argmin(mapping_f, min)
