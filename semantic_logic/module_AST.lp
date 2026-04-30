
statement
    ::bound_sym_list
    ::free_sym_list
    ::sub_statement_list

    ::all_statement_list
        |- statement.sub_statement_list = {}
            all_statement_list = {statement}
        |- statement.sub_statement_list \neq {}
            all_statement_list = {statement' \in statement.sub_statement_list => statement'.all_statement_list}

    ::all_bound_sym_list = {| statement' \in statement.all_statement_list => statement'.bound_sym_list}

    ::all_free_sym_list = {| statement' \in statement.all_statement_list => statement'.free_sym_list}

    ::active_free_sym_list = statement.all_free_sym_list - statement.all_bound_sym_list

statement~sym
    ::bound_sym_list = {}
    ::free_sym_list = {sym}
    ::sub_statement_list = {}

statement~equity_statement
    ::dst_sym
    ::src_statement
    ::bound_sym_list = {}
    ::free_sym_list = {equity_statement.dst_sym}
    ::sub_statement_list = {equity_statement.src_statement}

statement~call_statement
    ::call_sym
    ::argument_sym_list
    ::bound_sym_list = {}
    ::free_sym_list = call_statement.argument_sym_list \union {call_statement.call_sym}
    ::sub_statement_list = {}

statement~predicate_statement
PS = predicate_statement

statement~function_statement
FS = function_statement

statement~set_statement
    ::bound_sym_list
    ::free_sym_list = {}

    ::premise_equity_statement_list
    ::premise_PS_list
    ::target_PS_list
    ::sub_statement_list = set_statement.premise_equity_statement_list \union set_statement.premise_PS_list \union set_statement.target_PS_list

set_statement~quantified_statement
    ::quantifier_sym


