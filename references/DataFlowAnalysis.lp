@数据流分析data_flow
    @基本定义
        direction
        direction ~ forward
        direction ~ backward
        position
        position ~ in
        position ~ out
        # instr/block的插入点
        program_point
            ::node
            ::position
            ::init: {node, position} => program_point
                condition("default constructor")
        edge
            ::in_node
            ::out_node
            ::init: {in_node, out_node} => edge
                condition("constructor")
        graph
            # 单源点单终点的图
            ::nodes
            ::is_connected: {graph, node1, node2} => bool
            ::is_connected: {graph, edge} => bool
                bool = graph.is_connected(edge.in_node, edge.out_node)
            ::entry_node
            ::exit_node
            ::in_nodes: {graph, node} => nodes
                nodes = {| edge | edge.out_node = node | graph.is_connected(edge) | edge.in_node}
            ::out_nodes: {graph, node} => nodes
                nodes = {| edge | edge.in_node = node | graph.is_connected(edge) | edge.out_node}
            ::is_valid_path: {graph, path, direction} => bool
                ∀
                    |- direction = forward
                        bool = ∀{| i | path[i + 1] ∈ graph.out_nodes(path[i])}
                    |- direction = backward
                        bool = ∀{| i | path[i + 1] ∈ graph.in_nodes(path[i])}
            ::paths: {graph, direction} => paths
                # 从entry到exit(或反向)的paths
                ∀
                    |- direction = forward
                        paths = {| path | path[0] = graph.entry_node | path[-1] = graph.exit_node | graph.is_valid_path(path, direction) | path}
                    |- direction = backward
                        paths = {| path | path[0] = graph.exit_node | path[-1] = graph.entry_node | graph.is_valid_path(path, direction) | path}
            ::paths: {graph, src_node, dst_node, direction} => paths
                paths = {| path ∈ graph.paths(direction) | i ≤ j | path[i] = src_node | path[j] = dst_node | sub_path = path[i: j + 1] | sub_path}
            ::paths: {graph, node, direction} => paths
                ∀
                    |- direction = forward
                        paths = graph.paths(graph.entry_node, node, forward)
                    |- direction = backward
                        paths = graph.paths(graph.exit_node, node, backward)
            ::paths: {graph, program_point, direction} => paths
                node = program_point.node
                ∀
                    |- program_point.position = in
                        |- direction = forward
                            paths = {| path ∈ graph.paths(node, forward) | path[: -1]}
                        |- direction = backward
                            paths = graph.paths(node, backward)
                    |- program_point.position = out
                        |- direction = forward
                            paths = graph.paths(node, forward)
                        |- direction = backward
                            paths = {| path ∈ graph.paths(node, backward) | path[: -1]}
        df_state
            ::val: {df_state, program_point} => v
        # init df_state from boundary_val
        @data_flow核心定义
            data_flow
                # val-type
                ::V
                ::boundary_val: data_flow => v
                ::merge: {data_flow, v1, v2} => v
                ::direction
                    # 数据流分析方向
                ::transfer: {data_flow, path} => v1
                    # data-flow定义中只需要从entry出发的path的transfer函数
                ::merge: {data_flow, vals} => v
                    condition("vals is non-empty")
                    ∀
                        |- vals.size = 1
                            v = vals[0]
                        |- vals.size > 1
                            v1 = vals[0]
                            v2 = data_flow.merge(vals[1:])
                            v = data_flow.merge(v1, v2)
        @graph_data_flow定义
            data_flow
                ::graph_run_val: {data_flow, graph, program_point} => val
                    paths = graph.paths(program_point, data_flow.direction)
                    vals = {| path ∈ paths | data_flow.transfer(path)}
                    val = data_flow.merge(vals)
                ::graph_run: {data_flow, graph} => df_state
                    ∀{| node ∈ graph, position | program_point = (program_point :: init(node, position)) | df_state.val(program_point :: init(node, position)) = data_flow.graph_run_val(graph, program_point)}
        @program_data_flow定义
            # program包含一个graph
            graph ~ program
                ::is_valid_path: {program, path} => bool
                    condition("额外判断程序在真实过程中是否能执行到该条路径(若是反向路径，则reverse后以正向路径判断)")
            data_flow
                ::program_run_val: {data_flow, program, program_point} => val
                    program_graph = program
                    val = data_flow.graph_run_val(program_graph, program_point)
                ::program_run: {data_flow, program} => df_state
                    program_graph = program
                    df_state = data_flow.graph_run(program_graph)
        @algorithm_data_flow定义
            data_flow
                ::transfer: {data_flow, node, v} => v1
                    # 算法需要单个node的transfer函数
                    v1 = data_flow.transfer_f(node)(v)
                ::transfer: {data_flow, path, v} => v1
                    ∀
                        |- path.size = 0
                            v1 = v
                        |- path.size > 0
                            v' = data_flow.transfer(path[0], v)
                            v1 = data_flow.transfer(path[1:], v')
                ::transfer: {data_flow, path} => v
                    v = data_flow.transfer(path, data_flow.boundary_val)
                ::is_monotonous: data_flow => bool
                    # 所有node上的transfer函数都单调
                    bool = ∀{| node | unary_f = v -> data_flow.transfer(node, v) | unary_f.is_monotonous(data_flow.merge)}
                ∀{data_flow.is_monotonous}
                    # data_flow必须单调
                ::is_distributive: data_flow => bool
                    # 所有node上的transfer函数都distributive
                    bool = ∀{| node | unary_f = v -> data_flow.transfer(node, v) | unary_f.is_distributive(data_flow.merge)}
                ::step: {data_flow, graph, df_state} => df_state1
                    node ∈ graph.nodes
                    ∀
                        |- data_flow.direction = forward
                            | in_nodes = graph.in_nodes(node)
                            | vals = {| in_node ∈ in_nodes | df_state.val(program_point :: init(in_node, out))}
                            df_state1.val(program_point :: init(node, in)) = data_flow.merge(vals)
                            df_state1.val(program_point :: init(node, out)) = data_flow.transfer(node, df_state.val(program_point :: init(node, in)))
                        |- data_flow.direction = backward
                            | out_nodes = graph.out_nodes(node)
                            | vals = {| out_node ∈ out_nodes | df_state.val(program_point :: init(out_node, in))}
                            df_state1.val(program_point :: init(node, in)) = data_flow.transfer(node, df_state.val(program_point :: init(node, out)))
                            df_state1.val(program_point :: init(node, out)) = data_flow.merge(vals)
                ::steps: {data_flow, graph, df_state} => df_state1
                    df_state' = data_flow.step(graph, df_state)
                    ∀
                        | df_state' = df_state
                            df_state1 = df_state'
                        | df_state' ≠ df_state
                            df_state1 = data_flow.steps(graph, df_state')
                ::algorithm_run: {data_flow, graph} => df_state1
                    df_state0 = (df_state :: init(graph, data_flow.direction, data_flow.boundary_val))
                    df_state1 = data_flow.steps(graph, df_state0)
                ::algorithm_run_val: {data_flow, graph, program_point} => val
                    df_state' = data_flow.algorithm_run(graph)
                    val = df_state'.val(program_point)
        @data-flow定义与算法的关系
            ∀
                | data_flow
                | graph = program
                | graph ~ program
                | program_point
                | algorithm_val = data_flow.algorithm_run_val(graph, program_point)
                | graph_val = data_flow.graph_run_val(graph, program_point)
                | program_val = data_flow.program_run_val(program, program_point)
                ∀
                    |- data_flow.is_monotonous
                        # 若所有的转移函数是monotonous
                        (algorithm_val ≤ graph_val) ≤ program_val
                    |- data_flow.is_distributive
                        # 若所有的转移函数是distributive的，则算法计算的结果就是所有graph中可行路径的vals的交集
                        (algorithm_val = graph_val) ≤ program_val
        @集合型data-flow
            transfer_type
            transfer_type ~ add_before_kill
            transfer_type ~ kill_before_add
            # V是集合且transfer交替进行∪和disjoint时，data-flow在paths上有特殊性质
            data_flow ~ set_data_flow
                ∀{set_data_flow.V = set}  # value-type是集合，如exprs
                # merge function is either union or intersect
                set_data_flow.merge ∈ {∪, ∩}
                ::add_set: {set_data_flow, node} => set
                    # 如available-exprs中加入instr.src_expr
                ::kill_set: {set_data_flow, node} => set
                    # 如available-exprs中去掉instr.dst_var所对应的所有exprs
                ::transfer_type
                    # is union first or disjoint first
                ::transfer: {set_data_flow, node, set} => set1
                    # 相比于data_flow，set_data_flow的transfer有固定的模式
                    add_set = set_data_flow.add_set(node)
                    kill_set = set_data_flow.kill_set(node)
                    ∀
                        |- set_data_flow.transfer_type = add_before_kill
                            set1 = ((set ∪ add_set) - kill_set)
                        |- set_data_flow.transfer_type = kill_before_add
                            set1 = ((set - kill_set) ∪ add_set)
                ::transfer: {set_data_flow, path, set} => set1
                    ∀
                        |- path.size = 0
                            set1 = set
                        |- path.size > 0
                            set' = set_data_flow.transfer(path[0], set)
                            set1 = set_data_flow.transfer(path[1:], set')
                ::is_valid_sub_path: {set_data_flow, path, element} => bool
                    # path[0] generates element, path[1:] doesn't kill it
                    # So element exists at the path exit
                    is_added = ∀{element ∈ set_data_flow.add_set(path[0])}
                    is_killed = ∃{| node ∈ path[1:] | element ∈ set_data_flow.kill_set(node)}
                    bool = ∀{is_added, !is_killed}
                ::is_valid_path: {set_data_flow, path, element} => bool
                    bool = ∃{| i, path' = path[i:] | set_data_flow.is_valid_sub_path(path', element)}
                    # it's identical to data_flow constraint on the path transfer function
                    bool = ∀{element ∈ set_data_flow.transfer(path, set_data_flow.boundary_val)}
                # Core constraint, indicates the attribute each element satisfy in a program point
                ::is_valid_element: {set_data_flow, program, program_point, element} => bool
                    bool = ∀{element ∈ set_data_flow.program_run_val(program, program_point)}
                    # the contraint below indicates that exists-one-path or all-paths that can generate the given element and doesn't kill it
                    ∀
                        |- set_data_flow.merge = ∪
                            bool = ∃{| path ∈ program.paths(program_point, set_data_flow.direction) | set_data_flow.is_valid_path(path, element)}
                        |- set_data_flow.merge = ∩
                            bool = ∀{| path ∈ program.paths(program_point, set_data_flow.direction) | set_data_flow.is_valid_path(path, element)}
        @应用
            # 存在4种data-flow模式， {forward, backward} x {∪,  ∩}
            # <forward, ∪> = reaching
            # <forward, ∩> = available
            # <backward, ∪> = live
            # <backward, ∩> = anticipate
            @constant folding相关
                @定义
                    env_val_state
                    env_val_state ~ UNDEF
                    env_val_state ~ CONST
                    env_val_state ~ NOT_CONST
                    # 找出所有是常量的变量
                    env_val
                        # 程序执行时变量的可能值
                        ::state: env_val => env_val_state
                            # CONST表示必然等于的值
                            # UNDEF表示未被赋值
                            # NOT_CONST表示被外界输入变量影响
                        ::is_defined: env_val => bool
                            (bool = env_val.state) ≠ UNDEF
                        ::is_const: env_val => bool
                            bool = ∀{env_val.state = CONST}
                        ::const_val: env_val => val
                            ∀{| env_val.state ≠ CONST | val = null}
                    merge: {env_val1, env_val2} => env_val
                        ∀{semi_lattice :: merge}
                        val1 = env_val1
                        val2 = env_val2
                        val = env_val
                        ∀
                            | val1.state = CONST, val2.state = CONST
                                | val1 = val2
                                val = val1
                                | val1 ≠ val2
                                val.state = NOT_CONST
                            | ∃{| val' ∈ {val1, val2} | val'.state = NOT_CONST}
                            val.state = NOT_CONST
                                # 5种情况
                            | val1.state = CONST, val2.state = UNDEF
                            val = val1
                                # 某一个值UNDFE时，选择已有值
                            | val1.state = UNDEF, val2.state = CONST
                            val = val2
                env
                    # 程序执行时的变量环境
                    : {env, var} => env_val
                        # 当前状态下，var的值
                    ::init: input_vars => env
                        # 初始环境
                        ∀{| var ∈ input_vars | env(var).state = NOT_CONST}
                        ∀{| var ∉ input_vars | env(var).state = UNDEF}
                env :: run: {env, node} => env1
                    # 转移函数
                env :: run: {env, path} => env1
                    env1 = env.run(path[0]).run(path[1:])
                merge: {env1, env2} => env
                    # env的半格函数 是 env-val的半格函数的笛卡尔积
                    ∀{semi_lattice :: merge}
                    ∀{| var | env_val1 = env1(var), env_val2 = env2(var) | env_val = env(var) | env_val = merge(env_val1, env_val2)}
                program :: input_vars: program => vars
                program :: initial_env: program => env
                    env = (env :: init(program.input_vars))
                data_flow ~ const_folding_data_flow
                    const_folding_data_flow.direction = forward
                    const_folding_data_flow.boundary_val = (env :: init({}))
                    ::merge: {const_folding_data_flow, env1, env2} => env
                        env = merge(env1, env2)
                    ::transfer: {const_folding_data_flow, env, node} => env1
                        condition("根据node中instrs的情况更新map")
                        env1 = env.run(node)
        @instrs相关
            @reaching_instrs相关
                # 找到在instr处可能有用的所有instrs
                set_data_flow ~ reaching_instrs_data_flow
                    reaching_instrs_data_flow.V = instrs
                    reaching_instrs_data_flow.boundary_val = {}
                    reaching_instrs_data_flow.direction = forward
                    reaching_instrs_data_flow.merge = ∪
                    reaching_instrs_data_flow.transfer_type = kill_before_add
                    ::add_set: {reaching_instrs_data_flow, node} => instrs
                        instrs = {node.instr}
                    ::kill_set: {reaching_instrs_data_flow, node} => instrs
                        instrs = {| instr | instr.dst_var = node.instr.dst_var | instr}
            @available_instrs相关
                # 找到在instr处有用的所有instrs
                set_data_flow ~ available_instrs_data_flow
                    available_instrs_data_flow.V = instrs
                    available_instrs_data_flow.boundary_val = {}
                    available_instrs_data_flow.direction = forward
                    available_instrs_data_flow.merge = ∩
                    available_instrs_data_flow.transfer_type = kill_before_add
                    ::add_set: {available_instrs_data_flow, node} => instrs
                        instrs = {node.instr}
                    ::kill_set: {available_instrs_data_flow, node} => instrs
                        instrs = {| instr | instr.dst_var = node.instr.dst_var | instr}
        @vars相关
            @reaching_vars相关
                # 在instr处可能被定义的所有vars
                set_data_flow ~ reaching_vars_data_flow
                    reaching_vars_data_flow.V = vars
                    reaching_vars_data_flow.boundary_val = {}
                    reaching_vars_data_flow.merge = ∪
                    reaching_vars_data_flow.transfer_type = kill_before_add
                    ::add_set: {reaching_vars_data_flow, node} => vars
                        vars = {node.dst_var}
                    ::kill_set: {reaching_vars_data_flow, node} => vars
                        vars = {}
                    reaching_vars_data_flow.direction = forward
            @available_vars相关
                # 在instr处所有被定义的变量
                set_data_flow ~ available_vars_data_flow
                    available_vars_data_flow.V = vars
                    available_vars_data_flow.boundary_val = {}
                    available_vars_data_flow.merge = ∩
                    available_vars_data_flow.transfer_type = kill_before_add
                    ::add_set: {available_vars_data_flow, node} => vars
                        vars = {node.dst_var}
                    ::kill_set: {available_vars_data_flow, node} => vars
                        vars = {}
            @live_vars相关
                # 在instr处所有可能被后续使用的变量
                set_data_flow ~ live_vars_data_flow
                    live_vars_data_flow.direction = backward
                    live_vars_data_flow.V = vars
                    live_vars_data_flow.boundary_val = {}
                    live_vars_data_flow.merge = ∪
                    live_vars_data_flow.transfer_type = kill_before_add
                    ::add_set: {live_vars_data_flow, node} => vars
                        vars = node.src_expr.vars
                    ::kill_set: {live_vars_data_flow, node} => vars
                        vars = {node.dst_var}
                    live_vars_data_flow.direction = backward
            @anticipated_vars相关
                # 在instr处所有会被后续使用的变量
                set_data_flow ~ anticipated_vars_data_flow
                    anticipated_vars_data_flow.V = vars
                    anticipated_vars_data_flow.boundary_val = {}
                    anticipated_vars_data_flow.merge = ∩
                    anticipated_vars_data_flow.transfer_type = kill_before_add
                    ::add_set: {anticipated_vars_data_flow, node} => vars
                        vars = node.src_expr.vars
                    ::kill_set: {anticipated_vars_data_flow, node} => vars
                        vars = {node.dst_var}
                    anticipated_vars_data_flow.direction = backward
        @exprs相关
            @表达式相关
                expr
                    ::vars
                    ::op: {expr, vals} => val
                        vals.size = expr.vars.size
                        # 输入vars的值，计算结果值
                    ::equal(=): {expr, expr1} => bool
                        bool = ∀{expr.op = expr1.op, expr.vars = expr1.vars}
                expr ~ var
                    # 单个var表示的表达式
                    var.vars = {var}
                    var.op = vals -> vals[0]
                expr :: eval: {expr, env} => val
                    vals = {| var ∈ expr.vars | env(var)}
                    val = expr.op(vals)
                assign_expr
                    ::dst_var
                    ::src_expr
                    ::op
                    assign_expr.op = assign_expr.src_expr.op
                    ::src_vars
                    assign_expr.src_vars = assign_expr.src_expr.vars
            @表达式树expr_tree相关
                tree ~ expr_tree
                    # 表达式的语法树
                    ::children: expr_tree => expr_trees
                    ::expr_trees
                    expr_tree.expr_trees = expr_tree.children
                    ::op: {expr_tree, vals} => val
                        # 操作符函数
                        vals.size = expr_tree.expr_trees.size
                    ::val
                    expr_tree.val = expr_tree.op
                expr_tree ~ leaf
                    ∀{leaf.children.size = 0}
                    ::var
                    leaf.var = leaf.op
                expr_tree :: eval: {expr_tree, env} => val
                    # 给定一个变量环境，计算表达式的值
                    ∀
                        |- leaf ~ expr_tree
                            val = env(expr_tree.var)
                        |- else
                            vals = [sub_expr_tree.eval(env) | i, sub_expr_tree = expr_tree.children[i]]
                            operator = expr_tree.op
                            val = operator(vals)
                    leaf_vals = {| i | leaf = expr_tree.leafs[i] | var = leaf.var | env(var)}
                    val = expr_tree.full_op(leaf_vals)
                expr_tree :: is_equal: {expr_tree, expr_tree1} => bool
                    # 表达树的结构完全相等，最严格的equal比较
                    is_equal' = (expr_tree.op = expr_tree1.op)
                    is_equal'' = ∀{| i, sub_expr_tree = expr_tree.children[i], sub_expr_tree1 = expr_tree1.children[i] | sub_expr_tree.is_equal(sub_expr_tree1)}
                    bool = ∀{is_equal', is_equal''}
                    ∀{| env | expr_tree.eval(env) = expr_tree1.eval(env)}
                        # 任意输入变量值，计算的结果值都相等
                expr_tree :: is_semantic_equal: {expr_tree, expr_tree1} => bool
                    # 表达树的语义相等，考虑交换律、结合律等。更宽泛的equal比较
                    ∀{| env | expr_tree.eval(env) = expr_tree1.eval(env)}
                    # 任意输入变量值，计算的结果值都相等
                ∀{| expr_tree1, expr_tree2 | expr_tree1.is_equal(expr_tree2) | expr_tree1.is_semantic_equal(expr_tree2)}
                # 两个表达树，若结构相等，则语义必然相等
                expr_tree
                    ::init: var => expr_tree
                        # 单个var表示的表达式树
                        leaf ~ expr_tree
                        expr_tree.var = var
                expr ~ expr_tree
                    # 表达式树本质上就是一个表达式expr
                    expr_tree.vars = {| leaf ∈ expr_tree.leafs | leaf.var}
                    ::op: {expr_tree, vals} => val
                        split_vals: {expr_tree, vals} => vals_list
                            # 将vals分到各子树
                            ∀
                                |- leaf ~ expr_tree
                                    vals_list = [vals[0]]
                                |- else
                                    | first_child_leafs = expr_tree.children[0].leafs
                                    | vals' = vals[0: first_child_leafs.size]
                                    | remain_vals = vals[first_child_leafs.size:]
                                    vals_list = ([vals'] + split_vals(expr_tree, remain_vals))
                        ∀
                            # 将expr-tree展开后，基于叶节点变量的operator
                            |- leaf ~ expr_tree
                                val = vals[0]
                            |- else
                                | vals_list = split_vals(expr_tree, vals)
                                | vals'
                                | ∀{| i, sub_expr_tree = expr_tree.children[i] | sub_vals = vals_list[i] | vals'[i] = sub_expr_tree.full_op(sub_vals)}
                                | val = expr_tree.op(vals')
                                    # 先计算所有子树的值，再计算根节点的值
            @reaching_exprs相关
                # 在instr处可能被定义的exprs
                set_data_flow ~ reaching_exprs_data_flow
                    reaching_exprs_data_flow.V = exprs
                    reaching_exprs_data_flow.boundary_val = {}
                    reaching_exprs_data_flow.merge = ∪
                    reaching_exprs_data_flow.transfer_type = kill_before_add
                    ::add_set: {reaching_exprs_data_flow, node} => exprs
                        exprs = {node.src_expr}
                    ::kill_set: {reaching_exprs_data_flow, node} => exprs
                        exprs = {| expr | node.dst_var ∈ expr.vars | expr}
                    reaching_exprs_data_flow.direction = forward
            @available_exprs相关
                # 在instr处被定义的exprs
                set_data_flow ~ available_exprs_data_flow
                    available_exprs_data_flow.V = exprs
                    available_exprs_data_flow.boundary_val = {}
                    available_exprs_data_flow.merge = ∩
                    available_exprs_data_flow.transfer_type = kill_before_add
                    ::add_set: {available_exprs_data_flow, node} => exprs
                        exprs = {node.src_expr}
                    ::kill_set: {available_exprs_data_flow, node} => exprs
                        exprs = {| expr | node.dst_var ∈ expr.vars | expr}
                    available_exprs_data_flow.direction = forward
            @live_exprs相关
                # 在instr处可能被后续使用的exprs
                set_data_flow ~ live_exprs_data_flow
                    live_exprs_data_flow.V = exprs
                    live_exprs_data_flow.boundary_val = {}
                    live_exprs_data_flow.merge = ∪
                    live_exprs_data_flow.transfer_type = kill_before_add
                    ::add_set: {live_exprs_data_flow, node} => exprs
                        exprs = {node.src_expr}
                    ::kill_set: {live_exprs_data_flow, node} => exprs
                        exprs = {| expr | node.dst_var ∈ expr.vars | expr}
                    live_exprs_data_flow.direction = backward
            @anticipated_exprs相关
                # 在instr处会被后续使用的exprs
                set_data_flow ~ anticipated_exprs_data_flow
                    anticipated_exprs_data_flow.V = exprs
                    anticipated_exprs_data_flow.boundary_val = {}
                    anticipated_exprs_data_flow.merge = ∩
                    anticipated_exprs_data_flow.transfer_type = kill_before_add
                    ::add_set: {anticipated_exprs_data_flow, node} => exprs
                        exprs = {node.src_expr}
                    ::kill_set: {anticipated_exprs_data_flow, node} => exprs
                        exprs = {| expr | node.dst_var ∈ expr.vars | expr}
                    anticipated_exprs_data_flow.direction = backward
        @等价表达式expr_group相关
            exprs_set ~ expr_group
                # 表达式集合的并查集，每个expr都有等价的exprs
                ::exprs: {expr_group, expr} => exprs
                    # 与expr等价的exprs
                    exprs = {| exprs ∈ expr_group | expr ∈ exprs | exprs}
                ::vars: {expr_group, expr} => vars
                    # 与expr等价的vars
                    vars = {| var ∈ expr_group.exprs(expr) | var}
                ::is_equal: {expr_group, expr1, expr2} => bool
                    # 并查集操作，表示expr1与expr2是否等价
                    bool = {expr_group.exprs(expr1) = expr_group.exprs(expr2)}
            @available_expr_group相关
                # 在sintr处等价的exprs
                set_data_flow ~ available_expr_group_data_flow
                    available_expr_group_data_flow.V = expr_group
                    available_expr_group_data_flow.boundary_val = {}
                    ::merge: {available_expr_group_data_flow, expr_group1, expr_group2} => expr_group
                        # 半格合并函数，每对exprs在所有expr-groups都等价时才合并
                        ∀{| expr1, expr2 | expr_group.is_equal(expr1, expr2) = ∀{| expr_group' ∈ {expr_group1, expr_group2} | expr_group'.is_equal(expr1, expr2)}}
                    ::transfer: {available_expr_group_data_flow, expr_group, node} => expr_group1
                        # 转移函数，对每个节点的表达式进行处理
                        assign_expr = node.assign_expr
                        expr_group' = {| exprs ∈ expr_group | exprs' = {| expr ∈ exprs | assign_expr.dst_var !∈ expr.vars} | exprs'}
                        expr_group1 = expr_group'.add(assign_expr.dst_var, assign_expr.src_expr)
                    available_expr_group_data_flow.direction = forward
                is_equal: {program, path, expr1, expr2} => bool
                    # 在任何初始环境下，都等价的两个expr
                    bool = ∀{| initial_env ∈ program.initial_env | env = initial_env.run(path) | expr1.eval(env) = expr2.eval(env)}
                is_equal: {program, paths, expr1, expr2} => bool
                    # 在任何初始环境下，经过任何paths中的路径，都等价的两个expr
                    bool = ∀{| path ∈ paths | is_equal(program, path, expr1, expr2)}
                program :: exprs: {program, path, expr} => exprs
                    # 在任何初始环境下，都与expr等价的exprs
                    exprs = {| expr' | is_equal(program, path, expr, expr') | expr'}
                program :: exprs: {program, paths, expr} => exprs
                    # 在任何初始环境下，经过任何paths中的路径，都与expr等价的exprs
                    exprs = {| expr' | is_equal(program, paths, expr, expr') | expr'}
                program :: in_expr_group: {program, node} => expr_group
                    df_state = expr_group_data_flow.program_run(program)
                    expr_group = df_state.val(program_point :: init(node, in))
                    paths = {| path ∈ program.paths(node, forward) | path[: -1]}
                    ∀{| expr | expr_group.exprs(expr) = program.exprs(paths, expr)}
                        # 所有执行到该位置的环境下，expr_group中的每组expr都满足值相等的条件
                program :: out_expr_group: {program, node} => expr_group
                    df_state = expr_group_data_flow.program_run(program)
                    expr_group = df_state.val(program_point :: init(node, out))
                    paths = program.paths(node, forward)
                    ∀{| expr | expr_group.exprs(expr) = program.exprs(paths, expr)}
                        # 所有执行到该位置的环境下，expr_group中的每组expr都满足值相等的条件
            @reaching_expr_group相关
                # 在instr处可能等价的exprs
                set_data_flow ~ reaching_expr_group_data_flow(expr_group_data_flow)
                    reaching_expr_group_data_flow.V = expr_group
                    reaching_expr_group_data_flow.boundary_val = {}
                    ::merge: {expr_group_data_flow, expr_group1, expr_group2} => expr_group
                        # 半格合并函数，每对exprs在任意expr-group中等价时就合并
                        ∀{| expr1, expr2 | expr_group.is_equal(expr1, expr2) = ∃{| expr_group' ∈ {expr_group1, expr_group2} | expr_group'.is_equal(expr1, expr2)}}
                    ::transfer: {expr_group_data_flow, expr_group, node} => expr_group1
                        # 转移函数，对每个节点的表达式进行处理
                        assign_expr = node.assign_expr
                        expr_group' = {| exprs ∈ expr_group | exprs' = {| expr ∈ exprs | assign_expr.dst_var !∈ expr.vars} | exprs'}
                            # 去掉所有包含dst-var的表达式
                        expr_group1 = expr_group'.add(assign_expr.dst_var, assign_expr.src_expr)
                    reaching_expr_group_data_flow.direction = forward
        @paritial redundancy相关
            is_redundant_expr: {expr_groups, expr} => bool
                # 不同的path得到的expr_set都在expr上有dst-var（但dst-var不一定相同）
                # 从而可以在每个path末尾用相同的临时变量 "t = dst-var" 来统一
                bool = ∀{| expr_group ∈ expr_groups | expr_group.vars(expr) ≠ null}
            is_redundant_instr: {program, instr} => bool
                # 该instr的src_expr是否在每个path都有可表示的dst-var
                # 从而可以在每个分支用"t = dst-var"来统一
                in_instrs = program.in_nodes(instr)
                in_expr_groups = {| in_instr ∈ in_instrs | program.out_expr_group(in_instr)}
                bool = is_redundant_expr(in_expr_groups, instr.src_expr)
            is_partial_redundant_expr: {expr_groups, expr} => bool
                # 经过部分path得到的expr-group，有对应的dst-var
                # 从而可以在每个有对应的path末尾用“t = dst-var”
                # 在没有对应的path末尾用"t = expr"
                bool = ∃{| expr_group ∈ expr_groups | expr_group.vars(expr) ≠ null}
            is_partial_redundant_expr: {program, instr} => bool
                # 该instr的src_expr是否在某些path有可表示的dst-var
                in_instrs = program.in_nodes(instr)
                in_expr_groups = {| in_instr ∈ in_instrs | program.out_expr_group(in_instr)}
                bool = is_partial_redundant_expr(in_expr_groups, instr.src_expr)
            path :: is_redundant: path => bool
                # 是否存在两个instr读取相同的expr
                ∃{| i, j | path[i].src_expr = path[j].src_expr | ∀{| k ∈ [i + 1: j] | path[k].dst_var ∉ expr.vars}}
            program :: is_partial_redundant: program => bool
                ∃{| path ∈ program.paths | path.is_redundant}
        @lazy-code-motion相关
            # 用于消除partial-redundancy
            # anticipated, available, earliest, postponable, full_postponable, latest, used, insertable, replacible
            # anticipated => available
            # {anticipated, available} => earliest
            # earliest => postponable
            # {earliest, postponable} => full_postponable
            # full_postponable => latest
            # latest => used
            # {latest, used} => insertable # 插入t=expr的位置
            # {latest, used} => replacible  #将expr替代为t的位置
            # 使用latest定位插入点，使用replacible替换表达式
            # see above in @exprs相关
            set_data_flow ~ anticipated_exprs_data_flow
            program :: anticipated_exprs: {program, program_point} => exprs
                exprs = anticipated_exprs_data_flow.program_run_val(program, program_point)
            set_data_flow ~ anticipated_available_exprs_data_flow
                anticipated_available_exprs_data_flow.V = exprs
                anticipated_available_exprs_data_flow.boundary_val = {}
                anticipated_available_exprs_data_flow.direction = forward
                anticipated_available_exprs_data_flow.merge = ∩
                anticipated_available_exprs_data_flow.transfer_type = kill_before_add
                ::add_set: {anticipated_available_exprs_data_flow, node} => exprs
                    condition("add_set是node入口处的anticipated_exprs")
                    program = node.program
                    exprs = program.anticipated_exprs(program_point :: init(node, in))
                ::kill_set: {anticipated_available_exprs_data_flow, node} => exprs
                    exprs = {| expr | node.dst_var ∈ expr.vars | expr}
            program :: anticipated_available_exprs: {program, program_point} => exprs
                exprs = anticipated_available_exprs_data_flow.program_run_val(program, program_point)
            program :: earliest_exprs: {program, program_point} => exprs
                # earliest position to insert anticipated expr
                anticipated_exprs = program.anticipated_exprs(program_point)
                available_exprs = program.anticipated_available_exprs(program_point)
                # 在node处是最早anticipate的位置
                exprs = (anticipated_exprs - available_exprs)
            set_data_flow ~ postponable_exprs_data_flow
                postponable_exprs_data_flow.V = exprs
                postponable_exprs_data_flow.boundary_val = {}
                postponable_exprs_data_flow.direction = forward
                postponable_exprs_data_flow.merge = ∩
                postponable_exprs_data_flow.transfer_type = add_before_kill
                ::add_set: {postponable_exprs_data_flow, node} => exprs
                    program = node.program
                    exprs = program.earliest_exprs(program_point :: init(node, in))
                ::kill_set: {postponable_exprs_data_flow, node} => exprs
                    exprs = {node.src_expr}
            program :: postponable_exprs: {program, program_point} => exprs
                exprs = postponable_exprs_data_flow.program_run_val(program, program_point)
            program :: full_postponable_exprs: {program, program_point} => exprs
                earliest_exprs = program.earliest_exprs(program_point)
                postponable_exprs = program.postponable_exprs(program_point)
                exprs = (earliest_exprs ∪ postponable_exprs)
            program :: latest_exprs: {program, program_point} => exprs
                full_postponable_exprs = program.full_postponable_exprs(program_point)
                out_full_postponable_exprs = {| node' ∈ program.out_nodes(program_point.node) | program_point' = (program_point :: init(node', in)) | program.full_postponable_exprs(program_point')}
                ∀
                    |- program_point.position = in
                        # 在node处可postpone，且不能再往后postpone
                        exprs = (full_postponable_exprs ∩ (program_point.node.src_expr ∩ -∪{out_full_postponable_exprs}))
                    |- program_point.position = out
                        # TODO: is this correct?
                        exprs = (full_postponable_exprs ∩ (-∪{out_full_postponable_exprs}))
            set_data_flow ~ used_exprs_data_flow
                used_exprs_data_flow.V = exprs
                used_exprs_data_flow.boundary_val = {}
                used_exprs_data_flow.direction = backward
                used_exprs_data_flow.merge = ∪
                used_exprs_data_flow.transfer_type = add_before_kill
                ::add_set: {used_exprs_data_flow, node} => exprs
                    exprs = {node.src_expr}
                ::kill_set: {used_exprs_data_flow, node} => exprs
                    program = node.program
                    exprs = program.latest_exprs(program_point :: init(node, in))
            program :: used_exprs: {program, program_point} => exprs
                # 在program_point处，expr在后续被使用，且没有被插入temp-var(即latest_exprs)，也就是处于temp-var和expr-use之间
                exprs = used_exprs_data_flow.program_run_val(program, program_point)
            program :: insertable_exprs: {program, program_point} => exprs
                # 插入t = expr的位置
                latest_exprs = program.latest_exprs(program_point)
                node = program_point.node
                out_used_exprs = program.used_exprs(program_point :: init(node, out))
                ∀
                    |- program_point.position = in
                        # expr可以在node插入，且后续还会被使用时，可以插入
                        # 防止t=expr只被使用一次
                        exprs = (latest_exprs ∩ out_used_exprs)
                    |- program_point.position = out
                        condition("书中没讲")
            program :: replacible_exprs: {program, program_point} => exprs
                # 将expr替换为t的位置
                latest_exprs = program.latest_exprs(program_point)
                node = program_point.node
                out_used_exprs = program.used_exprs(program_point :: init(node, out))
                ∀
                    |- program_point.position = in
                        # 在node中，expr被使用，且 并非只有该node被单独插入并使用 时，可以进行替换
                        # 防止t=expr只被使用一次
                        exprs = (node.src_expr ∩ -(latest_exprs ∩ -out_used_exprs))
                    |- program_point.position = out
                        condition("书中没讲")
            # lazy-code-motion算法
            program :: expr_to_var_map: program => expr_to_var_map
            expr_to_var_map
                exprs = ∪{| node | program_point = (program_point :: init(node, in)) | program.insertable_exprs(program_point)}
            expr_to_var_map.keys = exprs
            condition("expr_to_var_map 给每个expr一个单独的var")
            program :: insert_exprs: program => program1
                expr_to_var_map = program.expr_to_var_map
                condition({expr_to_var_map, program.insertable_exprs}, "program1将所有node的insertable_exprs对应的temp_var=expr语句插入node.in")
            program :: replace_exprs: program => program1
                program1 = program.update(∀{| node ∈ program1 | condition("node将所有replacible_exprs替换成对应的temp_var")})
            program :: LCM: program => program1
                program' = program.replace_exprs
                program1 = program'.insert_exprs
                # 清除了redundancy
                !program1.is_partial_redundant
        @partial-dead相关
            path :: is_available_var: {path, var} => bool
                # var的定义在path中被使用
                ∃{| i | var ∈ path[i].src_expr.vars, ∀{| j < i | var ≠ path[j].dst_var}}
            path :: is_head_available: path => bool
                bool = path.is_head_available(path[1:], path[0].dst_var)
            path :: is_head_dead: path => bool
                bool = !path.is_head_available
            program :: is_dead: {program, node} => bool
                bool = ∀{| path ∈ program.paths(node, program.exit_node) | path.is_head_dead}
            program :: is_partial_dead: {program, node} => bool
                bool = ∃{| path ∈ program.paths(node, program.exit_node) | path.is_head_dead}
            program :: is_partial_dead: program => bool
                ∃{| node | program.is_partial_dead(node)}
            # partial_dead_elimination
            program :: PDE: program => program1
                # TODO: 对每个partial-dead-instr，先寻找可以往后推的位置delayable[I]，然后寻找最后的可插入位置latest[I]，然后先插入后删除
                !program1.is_partial_dead
        @应用：寻找earliest插入点
            set_data_flow ~ push_down_data_flow
                # 往前铺展
                # 需要铺展的df_state
                ::original_df_state
            program :: push_down_df_state: {program, df_state, program_point} => push_down_df_state
                push_down_df_state = push_down_data_flow(df_state).program_run(program)
            program :: earliest_df_state: {program, df_state, program_point} => earliest_df_state
                ∀
                    | program_point
                    | original_val = df_state.val(program_point)
                    | push_down_val = program.push_down_df_state.val(program_point)
                    earliest_df_state.val(program_point) = (original_val - push_down_val)
        @应用：寻找latest插入点
            set_data_flow ~ pull_up_data_flow
                # 往回铺展
                # 需要铺展的df_state
                ::original_df_state
            program :: pull_up_df_state: {program, df_state, program_point} => pull_up_df_state
                pull_up_df_state = pull_up_data_flow(df_state).program_run(program)
            program :: latest_df_state: {program, df_state, program_point} => latest_df_state
                ∀
                    | program_point
                    | original_val = df_state.val(program_point)
                    | pull_up_val = program.pull_up_df_state.val(program_point)
                    latest_df_state.val(program_point) = (original_val - pull_up_val)
