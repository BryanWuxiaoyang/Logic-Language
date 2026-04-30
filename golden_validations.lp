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