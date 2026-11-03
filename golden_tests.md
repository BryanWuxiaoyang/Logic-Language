# summary
below are the `source-text` and `expand_module(source-text)` golden pairs.
In addition `expand_module` should be closure-identical, i.e. `expand_module* = expand_module`

## implicit inheritance
"
List
-: (_list, _list1) => _list2
    _list2.size = (_list.size + _list1.size)
"
=
"
∀{
  Symbol ~ List
  Function ~ -
  ∀{
    | ^_list, ^_list1, ^_list2
    | ^_list2 = ^_list - ^_list1
    | List ~ ^_list
    | List ~ ^_list1
    List ~ ^_list2
  }
  ∀{
    | ^_list, ^_list1, ^_list2, ^tmpfunc_stmt0, ^tmpsize1, ^tmpadd2, ^tmpfunc_stmt3
    | ^_list2 = ^_list - ^_list1
    | ^tmpfunc_stmt0 = size(^_list2)
    | ^tmpsize1 = size(^_list)
    | ^tmpadd2 = ^tmpsize1 + ^_list1
    | ^tmpfunc_stmt3 = size(^tmpadd2)
    | List ~ ^_list
    | List ~ ^_list1
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
    | ^list, ^list1, ^list2, ^tmpfunc_stmt0, ^tmpsize1, ^tmpadd2, ^tmpfunc_stmt3
    | ^list2 = ^list - ^list1
    | ^tmpfunc_stmt0 = size(^list2)
    | ^tmpsize1 = size(^list)
    | ^tmpadd2 = ^tmpsize1 + ^list1
    | ^tmpfunc_stmt3 = size(^tmpadd2)
    ^tmpfunc_stmt0 = ^tmpfunc_stmt3
  }
}
"

## function-declaration
"
Sym
func: _sym => (_sym1, _sym2)
"
=
"
∀{
  Symbol ~ Sym
  Function ~ func
  ∀{
    | ^_sym, ^_sym1, ^_sym2, ^tmpfunc0, ^tmpvalue1, ^tmpvalue2
    | ^tmpfunc0 = func(^_sym)
    | ^tmpvalue1 = 0
    | ^_sym1 = ^tmpfunc0[^tmpvalue1]
    | ^tmpvalue2 = 1
    | ^_sym2 = ^tmpfunc0[^tmpvalue2]
    | Sym ~ ^_sym
    Tuple ~ ^tmpfunc0
    Value ~ ^tmpvalue1
    Value ~ ^tmpvalue2
    Sym ~ ^_sym1
    Sym ~ ^_sym2
  }
}
"

## function with tuple-target
"
Sym
func: _sym => (_sym1, _sym2)
    | P1(_sym)
    P2(_sym1, _sym2)
"
=
"
∀{
  Symbol ~ Sym
  Function ~ func
  ∀{
    | ^_sym, ^_sym1, ^_sym2, ^tmpfunc0, ^tmpvalue1, ^tmpvalue2
    | ^tmpfunc0 = func(^_sym)
    | ^tmpvalue1 = 0
    | ^_sym1 = ^tmpfunc0[^tmpvalue1]
    | ^tmpvalue2 = 1
    | ^_sym2 = ^tmpfunc0[^tmpvalue2]
    | Sym ~ ^_sym
    Tuple ~ ^tmpfunc0
    Value ~ ^tmpvalue1
    Value ~ ^tmpvalue2
    Sym ~ ^_sym1
    Sym ~ ^_sym2
  }
  ∀{
    | ^_sym, ^_sym1, ^_sym2, ^tmpfunc3, ^tmpvalue4, ^tmpvalue5
    | ^tmpfunc3 = func(^_sym)
    | ^tmpvalue4 = 0
    | ^_sym1 = ^tmpfunc3[^tmpvalue4]
    | ^tmpvalue5 = 1
    | ^_sym2 = ^tmpfunc3[^tmpvalue5]
    | Sym ~ ^_sym
    | P1(^_sym)
    P2(^_sym1, ^_sym2)
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
  | ^tmp03
  | ^tmp03 = {
    | ^logic_language_out0
    ∃{
      | ^sym, ^tmp00, ^tmp11, ^tmpfunc_stmt2
      | ^tmp00 = 0
      | ^tmp11 = 1
      | ^tmpfunc_stmt2 = ^sym + ^tmp11
      Value ~ ^tmp00
      Value ~ ^tmp11
      ^sym ≥ ^tmp00
      ^tmpfunc_stmt2 = ^logic_language_out0
    }
  }
  sym = ^tmp03
}
"

## class-declaration
"
Class
Sym
Class::func: (_class, ^sym1) => _sym2
"
=
"
∀{
  Symbol ~ Class
  Symbol ~ Sym
  Function ~ func
  ∀{
    | ^_class, ^sym1, ^_sym2
    | ^_sym2 = func(^_class, ^sym1)
    | Class ~ ^_class
    Sym ~ ^_sym2
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
    ::func: (_class, _val1) => _val2
"
=
"
∀{
  Symbol ~ Val
  Symbol ~ Class
  Function ~ func
  ∀{
    | ^_class, ^_val1, ^_val2
    | ^_val2 = func(^_class, ^_val1)
    | Class ~ ^_class
    | Val ~ ^_val1
    Val ~ ^_val2
  }
}
"

## class-call
"
Class
Class::func: (_class, ^sym1) => ^sym2
∀{| _class | ^sym | _class.func(^sym) = 0}
"
=
"
∀{
  Symbol ~ Class
  Function ~ func
  ∀{
    | ^_class, ^sym, ^tmpfunc_stmt0, ^tmpvalue_literal_stmt1
    | ^tmpfunc_stmt0 = func(^_class, ^sym)
    | ^tmpvalue_literal_stmt1 = 0
    | Class ~ ^_class
    Value ~ ^tmpvalue_literal_stmt1
    ^tmpfunc_stmt0 = ^tmpvalue_literal_stmt1
  }
}
"

## nested-function-declaration
"
func: _func => ^sym1
    | ^inner_func: ^sym2 => ^sym3
        P(^sym3)
    P(^inner_func)
"
=
"
∀{
  Function ~ func
  ∀{
    | ^_func, ^sym1, ^inner_func
    | ^sym1 = func(^_func)
    | Symbol ~ ^_func
    | Function ~ ^inner_func
    | ∀{
      | ^sym2, ^sym3
      | ^sym3 = ^inner_func(^sym2)
      P(^sym3)
    }
    P(^inner_func)
  }
}
"

## branch
"
func: ^sym1 => ^sym2
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
  Function ~ func
  ∀{
    | ^sym1, ^sym2, ^sym3
    | ^sym2 = func(^sym1)
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
  | ^tmptuple0, ^tmpset1, ^tmp1232, ^tmp13, ^tmptmp4, ^tmptuple5, ^tmpset6, ^tmptuple7, ^tmptuple8, ^tmpstring_literal9, ^tmp110, ^tmp211, ^tmpslice12, ^tmptuple13, ^tmp114, ^tmp215, ^tmpslice16, ^tmptuple17, ^tmp118, ^tmp219, ^tmpslice20, ^tmp121, ^tmp222, ^tmpslice23
  | ^tmptuple0 = (1, 2, 3)
  | ^tmpset1 = {1, 2, 3}
  | ^tmp1232 = "123"
  | ^tmp13 = '1'
  | ^tmptmp4 = '∀'
  | ^tmptuple5 = (1, 2, 3)
  | ^tmpset6 = {}
  | ^tmptuple7 = ()
  | ^tmptuple8 = ()
  | ^tmpstring_literal9 = ""
  | ^tmp110 = 1
  | ^tmp211 = 2
  | ^tmpslice12 = [:](^tmp110, ^tmp211)
  | ^tmptuple13 = (1, 2)
  | ^tmp114 = 1
  | ^tmp215 = 2
  | ^tmpslice16 = [:](^tmptuple13, ^tmp114, ^tmp215)
  | ^tmptuple17 = (1, 2)
  | ^tmp118 = 1
  | ^tmp219 = 2
  | ^tmpslice20 = [:](^tmptuple17, ^tmp118, ^tmp219)
  | ^tmp121 = 1
  | ^tmp222 = 2
  | ^tmpslice23 = [:](sym1, ^tmp121, ^tmp222)
  Tuple ~ ^tmptuple0
  Set ~ ^tmpset1
  String ~ ^tmp1232
  Char ~ ^tmp13
  Char ~ ^tmptmp4
  Tuple ~ ^tmptuple5
  Set ~ ^tmpset6
  Tuple ~ ^tmptuple7
  Tuple ~ ^tmptuple8
  String ~ ^tmpstring_literal9
  Value ~ ^tmp110
  Value ~ ^tmp211
  Tuple ~ ^tmptuple13
  Value ~ ^tmp114
  Value ~ ^tmp215
  Tuple ~ ^tmptuple17
  Value ~ ^tmp118
  Value ~ ^tmp219
  Value ~ ^tmp121
  Value ~ ^tmp222
  sym1 = ^tmptuple0
  sym2 = ^tmpset1
  sym3 = ^tmp1232
  sym4 = ^tmp13
  sym5 = ^tmptmp4
  sym6 = ^tmptuple5
  sym7 = ^tmpset6
  sym8 = ^tmptuple7
  sym9 = ^tmptuple8
  sym10 = ^tmpstring_literal9
  sym11 = ^tmpslice12
  sym12 = ^tmpslice16
  sym13 = ^tmpslice20
  sym14 = ^tmpslice23
}
"
