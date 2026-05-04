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
  | ^List
  Symbol ~ ^List
  Function ~ -
  ∀{
    | ^list, ^list1, ^list2
    | ^list2 = ^list - ^list1
    | ^List ~ ^list
    | ^List ~ ^list1
    ^List ~ ^list2
  }
  ∀{
    | ^list, ^list1, ^list2, ^tmpfunc_stmt0, ^tmpsize1, ^tmpsize2, ^tmpfunc_stmt3
    | ^list2 = ^list - ^list1
    | ^tmpfunc_stmt0 = size(^list2)
    | ^tmpsize1 = size(^list)
    | ^tmpsize2 = size(^list1)
    | ^tmpfunc_stmt3 = ^tmpsize1 + ^tmpsize2
    | ^List ~ ^list
    | ^List ~ ^list1
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
  | ^Sym
  Symbol ~ ^Sym
  Function ~ F
  ∀{
    | ^sym, ^sym1, ^sym2, ^tmpF0, ^tmpvalue1, ^tmpvalue2
    | ^tmpF0 = F(^sym)
    | ^tmpvalue1 = 0
    | ^sym1 = ^tmpF0[^tmpvalue1]
    | ^tmpvalue2 = 1
    | ^sym2 = ^tmpF0[^tmpvalue2]
    | ^Sym ~ ^sym
    Tuple ~ ^tmpF0
    Value ~ ^tmpvalue1
    Value ~ ^tmpvalue2
    ^Sym ~ ^sym1
    ^Sym ~ ^sym2
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
  | ^Sym
  Symbol ~ ^Sym
  Function ~ F
  ∀{
    | ^sym, ^sym1, ^sym2, ^tmpF0, ^tmpvalue1, ^tmpvalue2
    | ^tmpF0 = F(^sym)
    | ^tmpvalue1 = 0
    | ^sym1 = ^tmpF0[^tmpvalue1]
    | ^tmpvalue2 = 1
    | ^sym2 = ^tmpF0[^tmpvalue2]
    | ^Sym ~ ^sym
    Tuple ~ ^tmpF0
    Value ~ ^tmpvalue1
    Value ~ ^tmpvalue2
    ^Sym ~ ^sym1
    ^Sym ~ ^sym2
  }
  ∀{
    | ^sym, ^sym1, ^sym2, ^tmpF3, ^tmpvalue4, ^tmpvalue5
    | ^tmpF3 = F(^sym)
    | ^tmpvalue4 = 0
    | ^sym1 = ^tmpF3[^tmpvalue4]
    | ^tmpvalue5 = 1
    | ^sym2 = ^tmpF3[^tmpvalue5]
    | ^Sym ~ ^sym
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
  | ^Class, ^Sym
  Symbol ~ ^Class
  Symbol ~ ^Sym
  Function ~ func
  ∀{
    | ^class, ^sym1, ^sym2
    | ^sym2 = func(^class, ^sym1)
    | ^Class ~ ^class
    ^Sym ~ ^sym2
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
  | ^Val, ^Class
  Symbol ~ ^Val
  Symbol ~ ^Class
  Function ~ val
  ∀{
    | ^class, ^val'
    | ^val' = val(^class)
    | ^Class ~ ^class
    ^Val ~ ^val'
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
  | ^Val, ^Class
  Symbol ~ ^Val
  Symbol ~ ^Class
  Function ~ func
  ∀{
    | ^class, ^val1, ^val2
    | ^val2 = func(^class, ^val1)
    | ^Class ~ ^class
    | ^Val ~ ^val1
    ^Val ~ ^val2
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
  | ^Class
  Symbol ~ ^Class
  Function ~ func
  ∀{
    | ^class, ^sym, ^tmpfunc_stmt0, ^tmpvalue_literal_stmt1
    | ^tmpfunc_stmt0 = func(^class, ^sym)
    | ^tmpvalue_literal_stmt1 = 0
    | ^Class ~ ^class
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
  |- P1(^sym1)
    P2(^sym3)
  |- P3(^sym1)
    P4(^sym3)
  P5(^sym2)
"
=
"
∀{
  Function ~ F
  ∀{
    | ^sym1, ^sym2, ^sym3
    | ^sym2 = F(^sym1)
    | ∀{
      | P1(^sym1)
      P2(^sym3)
    }
    | ∀{
      | P3(^sym1)
      P4(^sym3)
    }
    P5(^sym2)
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

"