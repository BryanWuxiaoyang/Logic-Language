@seg_tree Core Logic Spec

    @定义
        range
            ::children: range => ranges
            
            ::is_leaf: range => bool
                bool = ∀{ range.children.size = 0 }
            
            ::leafs: range => ranges
                ∀
                    |- range.is_leaf
                        ranges = {range}
                    |- !range.is_leaf
                        ranges = ∪{ child.leafs | child ∈ range.children }

            ::intersect: {range, range1} => range2

            ::contains: {range, range1} => bool
                # range contains range1 iff intersection equals range1
                bool = ∀{ range.intersect(range1) = range1 }

            ::intersects: {range, range1} => bool
                bool = ∀{ range.intersect(range1) ≠ null }
            
            ::is_inside: {range, range1} => bool
                bool = ∀{range1.contains(range), range1 ≠ range}

            ::val: range => val
                # When range is a leaf, it has a value.
                # e.g. range[0:1] represents list-index=0
                range.is_leaf
            
            ::vals: range => vals
                ∀
                    |- range.is_leaf
                        vals = {range.val}
                    |- !range.is_leaf
                        vals = ∪{ child.vals | child ∈ range.children }

            ::init: val => range
                range.is_leaf
                range.val = val


        # a mapping function, but all keys are within a range
        mapping
            : {mapping, key} => val
            ::key_range: mapping => range
                range.vals = mapping.keys

            ::sub_mapping: {mapping, range} => mapping1
                ∀{ mapping1(key) = mapping(key) | key ∈ range.vals }

            ::children: mapping => mappings
                mappings = { mapping.sub_mapping(range') | range' ∈ mapping.key_range.children }
                
        

        # The modifier (such as +1, -1) applies to a V, and has a range-apply short-cut with O(1) time instead of O(n), 
        # which is used for lazy-push in seg_tree
        modifier
            # V is a value-type, with an add-op and identity-val
            # ∀{ V, V::+, V() }

            ::apply: {modifier, V} => V1

            ::apply_range: {modifier, range, V} => V1
                # mappings are mapping with mapping[range].sum = V
                mappings = { mapping
                    | V = sum({ mapping(key) | key ∈ range.vals })
                    | mapping }
                # mappings1 are mappings + modifier
                mappings1 = { mapping1
                    | mapping1 = mapping.update(∀{ mapping1(key) = modifier.apply(mapping(key)) | key ∈ range.vals })
                    | mapping ∈ mappings
                }
                # vals1 are all possible new vals
                vals1 = { sum{ mapping1(key) | key ∈ range.vals } | mapping1 ∈ mappings1 }
                # Constraint: Must ensure for all possible cases, the modified result val has only 1 possiblility.
                vals1.size = 1
                V1 = *vals1

            ::concat: {modifier, modifier1} => modifier'
                # first apply modifier, then apply modifier1
                ∀{ modifier'.apply(V) = modifier1.apply(modifier.apply(V)) | V }

        modifier~identity_modifier
            ::apply: {identity_modifier, V} => V1
                V1 = V
            ::apply_range: {identity_modifier, range, V} => V1
                V1 = V
            ::concat: {identity_modifier, modifier} => modifier1
                modifier1 = modifier

        modifier~chain_modifier
            ::modifiers

            ::init: modifiers => chain_modifier
            
            ::apply: {chain_modifier, V} => V1
                V' = chain_modifier.modifiers[0].apply(V)
                V1 = chain_modifier::init(chain_modifier.modifiers[1:]).apply(V')
            
            ::apply_range: {chain_modifier, range, V} => V1
                V' = chain_modifier.modifiers[0].apply_range(range, V)
                V1 = chain_modifier::init(chain_modifier.modifiers[1:]).apply_range(range, V')
            
            ::concat: {chain_modifier, modifier} => modifier1
                modifier1 = append_chain(chain_modifier, modifier)

        seg_tree
            ::children: seg_tree => nodes

            ::is_leaf: seg_tree => bool
                bool = seg_tree.range.is_leaf

            ::range: seg_tree => range
            
            # used for deducing .val from .base_val
            # used in lazy-update operation 
            ::modifier: seg_tree => modifier

            # V is a value-type, with a merge-op and identity-val
            # ∀{ V, V::+, V() }
            ::merge: {seg_tree, V1, V2} => V
            ::merge: {seg_tree, vals} => V
                ∀
                    |- vals.size = 1
                        V = vals[0]
                    |- vals.size > 1
                        | V1 = seg_tree.merge(vals[1:])
                        V = seg_tree.merge(vals[0], V1)

            # Cycle-constraints for .base_val and .val
            ::base_val: seg_tree => V
                ∀{ V = seg_tree.merge({ child.val | child ∈ seg_tree.children }) | !seg_tree.is_leaf }
            
            ::val: seg_tree => V
                ∀
                    |- seg_tree.is_leaf
                        V = seg_tree.modifier.apply(seg_tree.base_val)
                    |- !seg_tree.is_leaf
                        V = seg_tree.modifier.apply_range(seg_tree.range, seg_tree.base_val)

            # cycle-constraints of .base_mapping and .mapping
            ::base_mapping: seg_tree => mapping
                # The seg_tree represents a mapping (e.g. a list)
                # base_mapping is the mapping joined by all children
                ∀
                    |- seg_tree.is_leaf
                        mapping(seg_tree.range.val) = seg_tree.base_val
                    |- !seg_tree.is_leaf
                        mapping = ∪{ child.mapping | child ∈ seg_tree.children }
                mapping = ∪{ child.mapping | child ∈ seg_tree.children }
                seg_tree.base_val = seg_tree.merge(mapping.vals)

                # Important Constrant: When recursively searching children, 
                # we are searching for the sub-mapping of base-mapping, not mapping,
                # Therefore we need pushdown operation before searching children.
                ∀{ child.mapping = mapping.sub_mapping(child.range) | child ∈ seg_tree.children }
            
            ::mapping: seg_tree => mapping
                # The seg_tree represents a mapping (e.g. a list)
                # mapping is the mapping of base_mapping plus modifier
                mapping = seg_tree.base_mapping.update(∀{ mapping(key) = val
                    | val = seg_tree.modifier.apply(base_val)
                    | base_val = seg_tree.base_mapping(key)
                    | key ∈ seg_tree.range.vals })
                seg_tree.val = seg_tree.merge(mapping.vals)

            # Constructor
            ::init: mapping => seg_tree
                # Constraint: seg_tree must represent the given mapping
                seg_tree.mapping = mapping
                ∀
                    |- mapping.key_range.size = 1
                        seg_tree.range = mapping.key_range
                        seg_tree.base_val = mapping(mapping.key_range.val)
                        seg_tree.modifier = identity_modifier
                        seg_tree.children = {}
                    |- mapping.range.size > 1
                        seg_tree.children = {seg_tree::init(mapping') | mapping' ∈ mapping.children }
                        seg_tree.range = mapping.range
                        seg_tree.base_val = seg_tree.merge(mapping.vals)
                        seg_tree.modifier = identity_modifier

            ::push_down: seg_tree => seg_tree1
                # Constraint: seg_tree should represent the same mapping
                seg_tree1.mapping = seg_tree.mapping
                # When base_mapping = mapping, mapping is a join of children.mapping, 
                # so we can search for children recursively and gather the result.
                seg_tree1.mapping = seg_tree.base_mapping
                ∀
                    |- seg_tree.is_leaf
                        seg_tree1.base_val = seg_tree.modifier.apply(seg_tree.base_val)
                        seg_tree1.modifier = identity_modifier
                    |- !seg_tree.is_leaf
                        seg_tree1.children = ∀{
                            | child1.modifier = child.update(∀{child1.modifier = child.modifier.concat(seg_tree.modifier)})
                            | child ∈ seg_tree.children
                        }
                        seg_tree1.base_val = seg_tree.modifier.apply_range(seg_tree.range, seg_tree.base_val)
                        seg_tree1.modifier = identity_modifier

            ::get: {seg_tree, range} => V
                ∀{ seg_tree.contains(range) }
                V = seg_tree.merge({ seg_tree.mapping(i) | i ∈ range.vals })
                ∀
                    |- range = seg_tree.range
                        V = seg_tree.val
                    |- range = null
                        V = V()
                    |- range.is_inside(seg_tree.range)
                        # Note: we need push_down to align mapping with base_mapping,
                        # otherwise we are working on base_mapping, not mapping
                        seg_tree1 = seg_tree.push_down()
                        V = seg_tree.merge({ child.get(range) | child ∈ seg_tree1.children })

            ::get: {seg_tree, key} => V
                V = seg_tree.get(range(key))
            
            ::set: {seg_tree, range, modifier} => seg_tree1
                ∀{ seg_tree.contains(range) }
                seg_tree1.mapping = seg_tree.mapping.update(∀{seg_tree1.mapping(key) = val1
                    | val1 = modifier.apply(val)
                    | val = seg_tree.mapping(key)
                    | key ∈ range.vals })
                ∀
                    |- range = seg_tree.range
                        seg_tree1.modifier = seg_tree.modifier.concat(modifier)
                    |- range = null
                        seg_tree1 = seg_tree
                    |-  range.is_inside(seg_tree.range)
                        # Note: we need push_down to align mapping with base_mapping,
                        # otherwise we are working on base_mapping, not mapping
                        seg_tree' = seg_tree.push_down()
                        children' = { child.set(range, modifier) | child ∈ seg_tree'.children }
                        base_val' = seg_tree.merge({ child1.val | child1 ∈ seg_tree1.children })
                        seg_tree1 = seg_tree'.update(∀{ 
                            seg_tree1.children = children', 
                            seg_tree1.base_val = base_val' })

            ::set: {seg_tree, key, modifier} => seg_tree1
                seg_tree1 = seg_tree.set(range(key), modifier)

    @Applications
        modifier~assign_add_modifier
            # Used for integer add
            # ∀{int::V, V::+ = int::+, V() = 0}
            ::assign_val
            ::add_val

            #Constructor
            ::init: {assign_val, add_val} => assign_add_modifier
                assign_add_modifier.assign_val = assign_val
                assign_add_modifier.add_val = add_val

            ::apply: {assign_add_modifier, V} => V1
                ∀
                    |- assign_add_modifier.assign_val ≠ null
                        V1 = assign_add_modifier.assign_val + assign_add_modifier.add_val
                    |- assign_add_modifier.assign_val = null
                        V1 = V + assign_add_modifier.add_val

            ::apply_range: {assign_add_modifier, range, V} => V1
                ∀
                    |- assign_add_modifier.assign_val ≠ null
                        V1 = (assign_add_modifier.assign_val + assign_add_modifier.add_val) * range.size
                    |- assign_add_modifier.assign_val = null
                        V1 = V + assign_add_modifier.add_val * range.size

            ::concat: {assign_add_modifier, modifier} => modifier1
                # assignment overrides previous state; additive part accumulates
                ∀
                    |- identity_modifier~modifier
                        modifier1 = assign_add_modifier
                    |- assign_add_modifier~modifier
                        ∀
                            |- modifier.assign_val ≠ null
                                modifier1 = modifier
                            |- modifier.assign_val = null
                                |- assign_add_modifier.assign_val ≠ null
                                    modifier1 = assign_add_modifier::init(assign_val=assign_add_modifier.assign_val, add_val=assign_add_modifier.add_val + modifier.add_val)
                                |- assign_add_modifier.assign_val = null
                                    modifier1 = assign_add_modifier::init(add_val=assign_add_modifier.add_val + modifier.add_val)
                    |- else
                        modifier1 = chain_modifier::init([assign_add_modifier, modifier])


        modifier~mult_modifier
            # Used for integer multiply (sum-aggregation compatible)
            # ∀{int::V, V::+ = int::+, V() = 0}
            ::mult_val

            # Constructor
            ::init: mult_val => mult_modifier
                mult_modifier.mult_val = mult_val

            ::apply: {mult_modifier, V} => V1
                V1 = V * mult_modifier.mult_val

            ::apply_range: {mult_modifier, range, V} => V1
                V1 = V * mult_modifier.mult_val

            ::concat: {mult_modifier, modifier} => modifier1
                ∀
                    |- identity_modifier~modifier
                        modifier1 = mult_modifier
                    |- mult_modifier~modifier
                        modifier1 = mult_modifier::init(mult_val=mult_modifier.mult_val * modifier.mult_val)
                    |- else
                        modifier1 = chain_modifier::init([mult_modifier, modifier])


        seg_tree~add_seg_tree
        # Used for integer add/assign/multiply under sum aggregation
            ::add: {add_seg_tree, range, V} => basic_seg_tree1
                basic_seg_tree1 = add_seg_tree.set(range, assign_add_modifier::init(null, V))
            
            ::add: {add_seg_tree, key, V} => basic_seg_tree1
                basic_seg_tree1 = add_seg_tree.add(range(key), V)
            
            ::assign: {add_seg_tree, range, V} => basic_seg_tree1
                basic_seg_tree1 = add_seg_tree.set(range, assign_add_modifier::init(V, null))
            
            ::assign: {add_seg_tree, key, V} => basic_seg_tree1
                basic_seg_tree1 = add_seg_tree.assign(range(key), V)

            ::mult: {add_seg_tree, range, V} => basic_seg_tree1
                basic_seg_tree1 = add_seg_tree.set(range, mult_modifier::init(V))
            
            ::mult: {add_seg_tree, key, V} => basic_seg_tree1
                basic_seg_tree1 = add_seg_tree.mult(range(key), V)
