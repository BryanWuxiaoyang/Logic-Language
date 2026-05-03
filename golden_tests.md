# summary
below are the `source-text` and `compile(disassemble(source_text))` golden pairs

## implicit inheritance
"
List
-: (list, list1) => list2
        list2.size = (list.size + list1.size)
"
=
"
∀{
  | List
  | Symbol ~ List
  Function ~ -
  ∀{
    | list, list1, list2, __tmpfunc_stmt0, __tmpsize1, __tmpsize2, __tmpfunc_stmt3
    | list2 = list - list1
    | __tmpfunc_stmt0 = size(list2)
    | __tmpsize1 = size(list)
    | __tmpsize2 = size(list1)
    | __tmpfunc_stmt3 = __tmpsize1 + __tmpsize2
    | List ~ list
    | List ~ list1
    | List ~ list2
    __tmpfunc_stmt0 = __tmpfunc_stmt3
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
  Function ~ -
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
  Function ~ F
  ∀{
    | __sym, __sym1, __sym2, __tmpF0, __tmpvalue1, __tmpvalue2
    | __tmpF0 = F(__sym)
    | __tmpvalue1 = 0
    | __sym1 = __tmpF0[__tmpvalue1]
    | __tmpvalue2 = 1
    | __sym2 = __tmpF0[__tmpvalue2]
    | P1(__sym, __sym1, __sym2)
    | Tuple ~ __tmpF0
    | Value ~ __tmpvalue1
    | Value ~ __tmpvalue2
    P2(__sym1, __sym2)
  }
}
"
