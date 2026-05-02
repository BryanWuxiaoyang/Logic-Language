$import module_AST.lp

pred_stmt~eq_stmt
    ::dst_sym
    ::src_sym
    ::call_sym = '='
    ::arg_sym_list = [eq_stmt.dst_sym, eq_stmt.src_sym]

pred_stmt~inherit_stmt
    ::class_sym
    ::src_sym

    ::call_sym = '~'
    ::arg_sym_list = [inherit_stmt.class_sym, inherit_stmt.src_sym]

pred_stmt~and_stmt
    ::call_sym = '\land'

pred_stmt~or_stmt
    ::call_sym = '\lor'

pred_stmt~not_stmt
    ::call_sym = '\lnot'
    ::sym
    ::arg_sym_list [not_stmt.sym]

pred_stmt~implies_stmt
    ::premise_sym
    ::target_sym
    ::arg_sym_list = [implies_stmt.premise_sym, implies_stmt.target_sym]

pred_stmt~ne_stmt
    ::lhs_sym
    ::rhs_sym
    ::call_sym = '\ne'
    ::arg_sym_list = [ne_stmt.lhs_sym, ne_stmt.rhs_sym]

pred_stmt~gt_stmt
    ::lhs_sym
    ::rhs_sym
    ::call_sym = '>'
    ::arg_sym_list = [gt_stmt.lhs_sym, gt_stmt.rhs_sym]

pred_stmt~lt_stmt
    ::lhs_sym
    ::rhs_sym
    ::call_sym = '<'
    ::arg_sym_list = [lt_stmt.lhs_sym, lt_stmt.rhs_sym]

pred_stmt~ge_stmt
    ::lhs_sym
    ::rhs_sym
    ::call_sym = '>='
    ::arg_sym_list = [ge_stmt.lhs_sym, ge_stmt.rhs_sym]

pred_stmt~le_stmt
    ::lhs_sym
    ::rhs_sym
    ::call_sym = '<='
    ::arg_sym_list = [le_stmt.lhs_sym, le_stmt.rhs_sym]

pred_stmt~in_stmt
    ::elem_sym
    ::set_sym
    ::call_sym = '\in'
    ::arg_sym_list = [in_stmt.elem_sym, in_stmt.set_sym]

pred_stmt~notin_stmt
    ::elem_sym
    ::set_sym
    ::call_sym = '\notin'
    ::arg_sym_list = [notin_stmt.elem_sym, notin_stmt.set_sym]

pred_stmt~subset_stmt
    ::lhs_sym
    ::rhs_sym
    ::call_sym = '\subsetof'
    ::arg_sym_list = [subset_stmt.lhs_sym, subset_stmt.rhs_sym]

pred_stmt~notsubset_stmt
    ::lhs_sym
    ::rhs_sym
    ::call_sym = '\notsubsetof'
    ::arg_sym_list = [notsubset_stmt.lhs_sym, notsubset_stmt.rhs_sym]

pred_stmt~includedin_stmt
    ::lhs_sym
    ::rhs_sym
    ::call_sym = '\includedin'
    ::arg_sym_list = [includedin_stmt.lhs_sym, includedin_stmt.rhs_sym]

pred_stmt~notincludedin_stmt
    ::lhs_sym
    ::rhs_sym
    ::call_sym = '\notincludedin'
    ::arg_sym_list = [notincludedin_stmt.lhs_sym, notincludedin_stmt.rhs_sym]