$import module_AST.lp

Pred_stmt~Eq_stmt
Eq_stmt
    ::dst_sym
    ::src_sym
    ::call_sym: eq_stmt => sym
        sym = =
    ::arg_sym_list: eq_stmt => list
        list = [eq_stmt.dst_sym, eq_stmt.src_sym]

Pred_stmt~Inherit_stmt
Inherit_stmt
    ::class_sym
    ::src_sym

    ::call_sym: inherit_stmt => sym
        sym = ~
    ::arg_sym_list: inherit_stmt => list
        list = [inherit_stmt.class_sym, inherit_stmt.src_sym]

Pred_stmt~And_stmt
And_stmt
    ::call_sym: and_stmt => sym
        sym = \land

Pred_stmt~Or_stmt
Or_stmt
    ::call_sym: or_stmt => sym
        sym = \lor

Pred_stmt~Not_stmt
Not_stmt
    ::call_sym: not_stmt => sym
        sym = \lnot
    ::sym
    ::arg_sym_list: not_stmt => list
        list = [not_stmt.sym,]

Pred_stmt~Implies_stmt
Implies_stmt
    ::premise_sym
    ::target_sym
    ::arg_sym_list: implies_stmt => list
        list = [implies_stmt.premise_sym, implies_stmt.target_sym]

Pred_stmt~Ne_stmt
Ne_stmt
    ::lhs_sym
    ::rhs_sym
    ::call_sym: ne_stmt => sym
        sym = \ne
    ::arg_sym_list: ne_stmt => list
        list = [ne_stmt.lhs_sym, ne_stmt.rhs_sym]

Pred_stmt~Gt_stmt
Gt_stmt
    ::lhs_sym
    ::rhs_sym
    ::call_sym: gt_stmt => sym
        sym = >
    ::arg_sym_list: gt_stmt => list
        list = [gt_stmt.lhs_sym, gt_stmt.rhs_sym]

Pred_stmt~Lt_stmt
Lt_stmt
    ::lhs_sym
    ::rhs_sym
    ::call_sym: lt_stmt => sym
        sym = <
    ::arg_sym_list: lt_stmt => list
        list = [lt_stmt.lhs_sym, lt_stmt.rhs_sym]

Pred_stmt~Ge_stmt
Ge_stmt
    ::lhs_sym
    ::rhs_sym
    ::call_sym: ge_stmt => sym
        sym = >=
    ::arg_sym_list: ge_stmt => list
        list = [ge_stmt.lhs_sym, ge_stmt.rhs_sym]

Pred_stmt~Le_stmt
Le_stmt
    ::lhs_sym
    ::rhs_sym
    ::call_sym: le_stmt => sym
        sym = <=
    ::arg_sym_list: le_stmt => list
        list = [le_stmt.lhs_sym, le_stmt.rhs_sym]

Pred_stmt~In_stmt
In_stmt
    ::elem_sym
    ::set_sym
    ::call_sym: in_stmt => sym
        sym = \in
    ::arg_sym_list: in_stmt => list
        list = [in_stmt.elem_sym, in_stmt.set_sym]

Pred_stmt~Notin_stmt
Notin_stmt
    ::elem_sym
    ::set_sym
    ::call_sym: notin_stmt => sym
        sym = \notin
    ::arg_sym_list: notin_stmt => list
        list = [notin_stmt.elem_sym, notin_stmt.set_sym]

Pred_stmt~Subset_stmt
Subset_stmt
    ::lhs_sym
    ::rhs_sym
    ::call_sym: subset_stmt => sym
        sym = \subsetof
    ::arg_sym_list: subset_stmt => list
        list = [subset_stmt.lhs_sym, subset_stmt.rhs_sym]

Pred_stmt~Notsubset_stmt
Notsubset_stmt
    ::lhs_sym
    ::rhs_sym
    ::call_sym: notsubset_stmt => sym
        sym = \notsubsetof
    ::arg_sym_list: notsubset_stmt => list
        list = [notsubset_stmt.lhs_sym, notsubset_stmt.rhs_sym]

Pred_stmt~Includedin_stmt
Includedin_stmt
    ::lhs_sym
    ::rhs_sym
    ::call_sym: includedin_stmt => sym
        sym = \includedin
    ::arg_sym_list: includedin_stmt => list
        list = [includedin_stmt.lhs_sym, includedin_stmt.rhs_sym]

Pred_stmt~Notincludedin_stmt
Notincludedin_stmt
    ::lhs_sym
    ::rhs_sym
    ::call_sym: notincludedin_stmt => sym
        sym = \notincludedin
    ::arg_sym_list: notincludedin_stmt => list
        list = [notincludedin_stmt.lhs_sym, notincludedin_stmt.rhs_sym]
