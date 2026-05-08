# summary
below are the `source-text` and `expand_module(source-text)` golden pairs.
In addition `expand_module` should be closure-identical, i.e. `expand_module* = expand_module`

## implicit inheritance
"
List
-: (list, list1) => list2
    list2.size = (list.size + list1.size)
"
=
"
∀{
  Symbol ~ List
  Function ~ -
  ∀{
    | ^list, ^list1, ^list2
    | ^list2 = ^list - ^list1
    | List ~ ^list
    | List ~ ^list1
    List ~ ^list2
  }
  ∀{
    | ^list, ^list1, ^list2, ^tmpfunc_stmt0, ^tmpsize1, ^tmpsize2, ^tmpfunc_stmt3
    | ^list2 = ^list - ^list1
    | ^tmpfunc_stmt0 = size(^list2)
    | ^tmpsize1 = size(^list)
    | ^tmpsize2 = size(^list1)
    | ^tmpfunc_stmt3 = ^tmpsize1 + ^tmpsize2
    | List ~ ^list
    | List ~ ^list1
    ^tmpfunc_stmt0 = ^tmpfunc_stmt3
  }
}
"

## generated-sym exception
"
-: (^list, ^list1) => ^list2
    ^list2.size = (^list.size + ^list1.size)
"
=
"
∀{
  Function ~ -
  ∀{
    | ^list, ^list1, ^list2, ^tmpfunc_stmt0, ^tmpsize1, ^tmpsize2, ^tmpfunc_stmt3
    | ^list2 = ^list - ^list1
    | ^tmpfunc_stmt0 = size(^list2)
    | ^tmpsize1 = size(^list)
    | ^tmpsize2 = size(^list1)
    | ^tmpfunc_stmt3 = ^tmpsize1 + ^tmpsize2
    ^tmpfunc_stmt0 = ^tmpfunc_stmt3
  }
}
"

## function-declaration
"
Sym
F: sym => (sym1, sym2)
"
=
"
∀{
  Symbol ~ Sym
  Function ~ F
  ∀{
    | ^sym, ^sym1, ^sym2, ^tmpF0, ^tmpvalue1, ^tmpvalue2
    | ^tmpF0 = F(^sym)
    | ^tmpvalue1 = 0
    | ^sym1 = ^tmpF0[^tmpvalue1]
    | ^tmpvalue2 = 1
    | ^sym2 = ^tmpF0[^tmpvalue2]
    | Sym ~ ^sym
    Tuple ~ ^tmpF0
    Value ~ ^tmpvalue1
    Value ~ ^tmpvalue2
    Sym ~ ^sym1
    Sym ~ ^sym2
  }
}
"

## function with tuple-target
"
Sym
F: sym => (sym1, sym2)
    | P1(sym)
    P2(sym1, sym2)
"
=
"
∀{
  Symbol ~ Sym
  Function ~ F
  ∀{
    | ^sym, ^sym1, ^sym2, ^tmpF0, ^tmpvalue1, ^tmpvalue2
    | ^tmpF0 = F(^sym)
    | ^tmpvalue1 = 0
    | ^sym1 = ^tmpF0[^tmpvalue1]
    | ^tmpvalue2 = 1
    | ^sym2 = ^tmpF0[^tmpvalue2]
    | Sym ~ ^sym
    Tuple ~ ^tmpF0
    Value ~ ^tmpvalue1
    Value ~ ^tmpvalue2
    Sym ~ ^sym1
    Sym ~ ^sym2
  }
  ∀{
    | ^sym, ^sym1, ^sym2, ^tmpF3, ^tmpvalue4, ^tmpvalue5
    | ^tmpF3 = F(^sym)
    | ^tmpvalue4 = 0
    | ^sym1 = ^tmpF3[^tmpvalue4]
    | ^tmpvalue5 = 1
    | ^sym2 = ^tmpF3[^tmpvalue5]
    | Sym ~ ^sym
    | P1(^sym)
    P2(^sym1, ^sym2)
  }
}
"

## image-set
"
sym = {| ^sym | ^sym >= 0 => ^sym + 1}
"
=
"
∀{
  | ^tmpmodule03
  | ^tmpmodule03 = {
    | ^logic_language_out0
    ∃{
      | ^sym, ^tmp00, ^tmp11, ^tmpadd2
      | ^tmp00 = 0
      | ^tmp11 = 1
      | ^tmpadd2 = ^sym + ^tmp11
      | ^sym ≥ ^tmp00
      Value ~ ^tmp00
      Value ~ ^tmp11
      ^logic_language_out0 = ^tmpadd2
    }
  }
  sym = ^tmpmodule03
}
"

## class-declaration
"
Class
Sym
Class::func: (class, ^sym1) => sym2
"
=
"
∀{
  Symbol ~ Class
  Symbol ~ Sym
  Function ~ func
  ∀{
    | ^class, ^sym1, ^sym2
    | ^sym2 = func(^class, ^sym1)
    | Class ~ ^class
    Sym ~ ^sym2
  }
}
"

## class-field
"
Val
Class
Class::val
"
=
"
∀{
  Symbol ~ Val
  Symbol ~ Class
  Function ~ val
  ∀{
    | ^_class, ^_val
    | ^_val = val(^_class)
    | Class ~ ^_class
    Val ~ ^_val
  }
}
"

## class-body
"
Val
Class
    ::func: (class, val1) => val2
"
=
"
∀{
  Symbol ~ Val
  Symbol ~ Class
  Function ~ func
  ∀{
    | ^class, ^val1, ^val2
    | ^val2 = func(^class, ^val1)
    | Class ~ ^class
    | Val ~ ^val1
    Val ~ ^val2
  }
}
"

## class-call
"
Class
Class::func: (class, ^sym1) => ^sym2
∀{| class | ^sym | class.func(^sym) = 0}
"
=
"
∀{
  Symbol ~ Class
  Function ~ func
  ∀{
    | ^class, ^sym, ^tmpfunc_stmt0, ^tmpvalue_literal_stmt1
    | ^tmpfunc_stmt0 = func(^class, ^sym)
    | ^tmpvalue_literal_stmt1 = 0
    | Class ~ ^class
    Value ~ ^tmpvalue_literal_stmt1
    ^tmpfunc_stmt0 = ^tmpvalue_literal_stmt1
  }
}
"

## nested-function-declaration
"
F: func => ^sym1
    | func: ^sym2 => ^sym3
        P(^sym3)
    P(func)
"
=
"
∀{
  Function ~ F
  ∀{
    | ^func, ^sym1
    | ^sym1 = F(^func)
    | Function ~ ^func
    | ∀{
      | ^sym2, ^sym3
      | ^sym3 = ^func(^sym2)
      P(^sym3)
    }
    P(^func)
  }
}

"

## branch
"
F: ^sym1 => ^sym2
    | ^sym3
    | \all
        |- P1(^sym1)
            P2(^sym3)
        |- P3(^sym1)
            P4(^sym3)
    |- P5(^sym1)
        P6(^sym3)
    |- P7(^sym1)
        P8(^sym3)
"
=
"
∀{
  Function ~ F
  ∀{
    | ^sym1, ^sym2, ^sym3
    | ^sym2 = F(^sym1)
    | ∀{
      ∀{
        | P1(^sym1)
        P2(^sym3)
      }
      ∀{
        | P3(^sym1)
        P4(^sym3)
      }
    }
    ∀{
      | P5(^sym1)
      P6(^sym3)
    }
    ∀{
      | P7(^sym1)
      P8(^sym3)
    }
  }
}
"

## literals
"
sym1 = (1, 2, 3)
sym2 = {1, 2, 3}
sym3 = "123"
sym4 = '1'
sym5 = '\all'
sym6 = [1, 2, 3]
sym7 = {}
sym8 = [,] # empty list
sym9 = ()
sym10 = ""
sym11 = [1: 2]
sym12 = [1, 2][1: 2]
sym13 = (1, 2)[1: 2]
sym14 = sym1[1: 2]
"
=
"
∀{
  | ^tmp1_2_30, ^tmp1_2_31, ^tmpfunc_stmt2, ^tmpvalue_literal_stmt3, ^tmp04, ^tmpfunc_stmt5, ^tmpchar_literal_stmt6, ^tmp17, ^tmpfunc_stmt8, ^tmpchar_literal_stmt9, ^tmp210, ^tmpfunc_stmt11, ^tmpchar_literal_stmt12, ^tmp113, ^tmptmp14, ^tmp1_2_315, ^tmptmp16, ^tmptmp17, ^tmptmp18, ^tmpfunc_stmt19, ^tmpvalue_literal_stmt20, ^tmp121, ^tmp222, ^tmp1_223, ^tmp1_224, ^tmp125, ^tmp226, ^tmp1_2_1_227, ^tmp1_228, ^tmp129, ^tmp230, ^tmp1_2_1_231, ^tmp132, ^tmp233, ^tmpsym1_1_234
  | ^tmp1_2_30 = (1, 2, 3)
  | ^tmp1_2_31 = {1, 2, 3}
  | ^tmpfunc_stmt2 = size(sym3)
  | ^tmpvalue_literal_stmt3 = 3
  | ^tmp04 = 0
  | ^tmpfunc_stmt5 = sym3[^tmp04]
  | ^tmpchar_literal_stmt6 = '1'
  | ^tmp17 = 1
  | ^tmpfunc_stmt8 = sym3[^tmp17]
  | ^tmpchar_literal_stmt9 = '2'
  | ^tmp210 = 2
  | ^tmpfunc_stmt11 = sym3[^tmp210]
  | ^tmpchar_literal_stmt12 = '3'
  | ^tmp113 = '1'
  | ^tmptmp14 = '∀'
  | ^tmp1_2_315 = (1, 2, 3)
  | ^tmptmp16 = {}
  | ^tmptmp17 = ()
  | ^tmptmp18 = ()
  | ^tmpfunc_stmt19 = size(sym10)
  | ^tmpvalue_literal_stmt20 = 0
  | ^tmp121 = 1
  | ^tmp222 = 2
  | ^tmp1_223 = [:](^tmp121, ^tmp222)
  | ^tmp1_224 = (1, 2)
  | ^tmp125 = 1
  | ^tmp226 = 2
  | ^tmp1_2_1_227 = [:](^tmp1_224, ^tmp125, ^tmp226)
  | ^tmp1_228 = (1, 2)
  | ^tmp129 = 1
  | ^tmp230 = 2
  | ^tmp1_2_1_231 = [:](^tmp1_228, ^tmp129, ^tmp230)
  | ^tmp132 = 1
  | ^tmp233 = 2
  | ^tmpsym1_1_234 = [:](sym1, ^tmp132, ^tmp233)
  Tuple ~ ^tmp1_2_30
  Set ~ ^tmp1_2_31
  Value ~ ^tmpvalue_literal_stmt3
  Value ~ ^tmp04
  Char ~ ^tmpchar_literal_stmt6
  Value ~ ^tmp17
  Char ~ ^tmpchar_literal_stmt9
  Value ~ ^tmp210
  Char ~ ^tmpchar_literal_stmt12
  Char ~ ^tmp113
  Char ~ ^tmptmp14
  Tuple ~ ^tmp1_2_315
  Set ~ ^tmptmp16
  Tuple ~ ^tmptmp17
  Tuple ~ ^tmptmp18
  Value ~ ^tmpvalue_literal_stmt20
  Value ~ ^tmp121
  Value ~ ^tmp222
  Tuple ~ ^tmp1_224
  Value ~ ^tmp125
  Value ~ ^tmp226
  Tuple ~ ^tmp1_228
  Value ~ ^tmp129
  Value ~ ^tmp230
  Value ~ ^tmp132
  Value ~ ^tmp233
  sym1 = ^tmp1_2_30
  sym2 = ^tmp1_2_31
  String ~ sym3
  ^tmpfunc_stmt2 = ^tmpvalue_literal_stmt3
  ^tmpfunc_stmt5 = ^tmpchar_literal_stmt6
  ^tmpfunc_stmt8 = ^tmpchar_literal_stmt9
  ^tmpfunc_stmt11 = ^tmpchar_literal_stmt12
  Char ~ sym4
  sym4 = ^tmp113
  Char ~ sym5
  sym5 = ^tmptmp14
  sym6 = ^tmp1_2_315
  sym7 = ^tmptmp16
  sym8 = ^tmptmp17
  sym9 = ^tmptmp18
  String ~ sym10
  ^tmpfunc_stmt19 = ^tmpvalue_literal_stmt20
  sym11 = ^tmp1_223
  sym12 = ^tmp1_2_1_227
  sym13 = ^tmp1_2_1_231
  sym14 = ^tmpsym1_1_234
}
"
