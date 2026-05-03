# summary
below are the `source-text` and `compile(disassemble(source_text))` golden pairs

##
"
val ~ min_val
∀{| val1 | val1 ≥ min_val}
"
= 
"
∀{
val ~ min_val
∀{
  | val1
  | sym ~ val1
  | val ~ val1
  val1 ≥ min_val
  }
}
"

## implicit inheritance & name-alias
"
-: (list, list1) => list2
        list2.size = (list.size + list1.size)
" 
= 
"
∀{
    function~-
    ∀{
        | __list, list1, list2
        | list2 = -(__list, list1)
        | list~__list
        | list~list1
        | __tmp_size = size(__list)
        | __tmp_size1 = size(list1)
        | __tmp_size2 = size(list2)
        | __tmp_size2' = +(__tmp_size, __tmp_size1)
        list~list2
        __tmp_size2 = __tmp_size2'
    }
}
"

## generated-sym exception
"
-: (__list, __list1) => __list2
        __list2.size = (__list.size + __list1.size)
"
=
"
∀{
    function ~ -
    ∀{
        | __list, __list1, __list2, __tmpfunc_stmt0, __tmpsize1, __tmpsize2, __tmpfunc_stmt3
        | __list2 = __list - __list1
        | __tmpfunc_stmt0 = size(__list2)
        | __tmpsize1 = size(__list)
        | __tmpsize2 = size(__list1)
        | __tmpfunc_stmt3 = __tmpsize1 + __tmpsize2
        __tmpfunc_stmt0 = __tmpfunc_stmt3
    }
}
"

## tuple-target
"
F: __sym => (__sym1, __sym2)
    | P1(__sym, __sym1, __sym2)
    P2(__sym1, __sym2)
"
=
"
∀{
  function ~ F
  ∀{
    | __sym, __sym1, __sym2, __tmpF0, __tmpvalue1, __tmpvalue2
    | __tmpF0 = F(__sym)
    | __tmpvalue1 = 0
    | __sym1 = __tmpF0[__tmpvalue1]
    | __tmpvalue2 = 1
    | __sym2 = __tmpF0[__tmpvalue2]
    | tuple ~ __tmpF0
    | P1(__sym, __sym1, __sym2)
    P2(__sym1, __sym2)
  }
}
"