# brace vs non-brace

# conflict-sym-elimination, implicit-inheritance, symbol-global-inheritance
\all
    # original
    \all
        object
        \all
            | symbol
            | sym
            | object
            | object1
            | P1(object1)
            P2(object1)
    # expanded target
    \all
        object
        \all
            | object1
            | symbol~object1
            | object~object1
            | P1(object1)
            P2(object1)

# function-semantics
\all
    # original
    \all
        object
        F: (object, object1) => object2
            | P1(object)
            P2(object2)
    # target
    \all
        object
        \all
            | __object, object1, object2
            | object~__object
            | object~object1
            | object2 = F(__object, object1)
            | P1(__object)
            object~object2
            P2(object2)

# implicit-declare-sym
\all
    #original
    \all
        | x
        | sym1 \ne x
        P(sym1)
    #target
    \all
        | x
        | sym1
        | sym1 \ne x
        P(sym1)

# collection implicit-inheritance
\all
    object
    # original plural collection
    \all
        prefix_objects
    # expanded plural collection target
    \all
        | prefix_objects
        | sym~prefix_objects
        | prefix_objects~prefix_objects
        | set~prefix_objects
        \all{| prefix_objects_item | prefix_objects_item \in prefix_objects | object~prefix_objects_item}

    # original list collection
    \all
        prefix_object_list
    # expanded list collection target
    \all
        | prefix_object_list
        | sym~prefix_object_list
        | prefix_object_list~prefix_object_list
        | list~prefix_object_list
        | tuple~prefix_object_list
        \all{| prefix_object_list_item | prefix_object_list_item \in prefix_object_list | object~prefix_object_list_item}
