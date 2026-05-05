$import standard_library.lp
$import module_AST.lp

Pred_stmt~Eq_stmt
Eq_stmt
    ::dst_sym
    ::src_sym
    ::call_sym: _eq_stmt => _eq_call_sym
        _eq_call_sym = =
    ::arg_sym_list: _eq_stmt => _list
        _list = [_eq_stmt.dst_sym, _eq_stmt.src_sym]

Pred_stmt~Inherit_stmt
Inherit_stmt
    ::class_sym
    ::src_sym

    ::call_sym: _inherit_stmt => _inherit_call_sym
        _inherit_call_sym = ~
    ::arg_sym_list: _inherit_stmt => _list
        _list = [_inherit_stmt.class_sym, _inherit_stmt.src_sym]

Pred_stmt~And_stmt
And_stmt
    ::call_sym: _and_stmt => _and_call_sym
        _and_call_sym = \land

Pred_stmt~Or_stmt
Or_stmt
    ::call_sym: _or_stmt => _or_call_sym
        _or_call_sym = \lor

Pred_stmt~Not_stmt
Not_stmt
    ::call_sym: _not_stmt => _not_call_sym
        _not_call_sym = \lnot
    ::sym
    ::arg_sym_list: _not_stmt => _list
        _list = [_not_stmt.sym,]

Pred_stmt~Implies_stmt
Implies_stmt
    ::premise_sym
    ::target_sym
    ::arg_sym_list: _implies_stmt => _list
        _list = [_implies_stmt.premise_sym, _implies_stmt.target_sym]

Pred_stmt~Ne_stmt
Ne_stmt
    ::lhs_sym
    ::rhs_sym
    ::call_sym: _ne_stmt => _ne_call_sym
        _ne_call_sym = \ne
    ::arg_sym_list: _ne_stmt => _list
        _list = [_ne_stmt.lhs_sym, _ne_stmt.rhs_sym]

Pred_stmt~Gt_stmt
Gt_stmt
    ::lhs_sym
    ::rhs_sym
    ::call_sym: _gt_stmt => _gt_call_sym
        _gt_call_sym = >
    ::arg_sym_list: _gt_stmt => _list
        _list = [_gt_stmt.lhs_sym, _gt_stmt.rhs_sym]

Pred_stmt~Lt_stmt
Lt_stmt
    ::lhs_sym
    ::rhs_sym
    ::call_sym: _lt_stmt => _lt_call_sym
        _lt_call_sym = <
    ::arg_sym_list: _lt_stmt => _list
        _list = [_lt_stmt.lhs_sym, _lt_stmt.rhs_sym]

Pred_stmt~Ge_stmt
Ge_stmt
    ::lhs_sym
    ::rhs_sym
    ::call_sym: _ge_stmt => _ge_call_sym
        _ge_call_sym = >=
    ::arg_sym_list: _ge_stmt => _list
        _list = [_ge_stmt.lhs_sym, _ge_stmt.rhs_sym]

Pred_stmt~Le_stmt
Le_stmt
    ::lhs_sym
    ::rhs_sym
    ::call_sym: _le_stmt => _le_call_sym
        _le_call_sym = <=
    ::arg_sym_list: _le_stmt => _list
        _list = [_le_stmt.lhs_sym, _le_stmt.rhs_sym]

Pred_stmt~In_stmt
In_stmt
    ::elem_sym
    ::set_sym
    ::call_sym: _in_stmt => _in_call_sym
        _in_call_sym = \in
    ::arg_sym_list: _in_stmt => _list
        _list = [_in_stmt.elem_sym, _in_stmt.set_sym]

Pred_stmt~Notin_stmt
Notin_stmt
    ::elem_sym
    ::set_sym
    ::call_sym: _notin_stmt => _notin_call_sym
        _notin_call_sym = \notin
    ::arg_sym_list: _notin_stmt => _list
        _list = [_notin_stmt.elem_sym, _notin_stmt.set_sym]

Pred_stmt~Subset_stmt
Subset_stmt
    ::lhs_sym
    ::rhs_sym
    ::call_sym: _subset_stmt => _subset_call_sym
        _subset_call_sym = \subsetof
    ::arg_sym_list: _subset_stmt => _list
        _list = [_subset_stmt.lhs_sym, _subset_stmt.rhs_sym]

Pred_stmt~Notsubset_stmt
Notsubset_stmt
    ::lhs_sym
    ::rhs_sym
    ::call_sym: _notsubset_stmt => _notsubset_call_sym
        _notsubset_call_sym = \notsubsetof
    ::arg_sym_list: _notsubset_stmt => _list
        _list = [_notsubset_stmt.lhs_sym, _notsubset_stmt.rhs_sym]

Pred_stmt~Includedin_stmt
Includedin_stmt
    ::lhs_sym
    ::rhs_sym
    ::call_sym: _includedin_stmt => _includedin_call_sym
        _includedin_call_sym = \includedin
    ::arg_sym_list: _includedin_stmt => _list
        _list = [_includedin_stmt.lhs_sym, _includedin_stmt.rhs_sym]

Pred_stmt~Notincludedin_stmt
Notincludedin_stmt
    ::lhs_sym
    ::rhs_sym
    ::call_sym: _notincludedin_stmt => _notincludedin_call_sym
        _notincludedin_call_sym = \notincludedin
    ::arg_sym_list: _notincludedin_stmt => _list
        _list = [_notincludedin_stmt.lhs_sym, _notincludedin_stmt.rhs_sym]
