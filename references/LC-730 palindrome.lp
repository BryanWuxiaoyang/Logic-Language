@LC-730  Count Different Palindromic Subsequences
    @定义
        str::subseq: {str, ids} => subseq
            ids.is_strict_sorted
            ∀{ subseq[k] = str[ids[k]] | k }

        str::subseqs: str => subseqs
            subseqs = { subseq
            | subseq = str.subseq(ids)
            | ids.is_strict_sorted }

        str::pal_subseqs: str => subseqs
            subseqs = { subseq
            | subseq ∈ str.subseqs
            | subseq.size > 0
            | subseq.is_palindrome }

        str::pal_subseqs: {str, i, j} => subseqs
            subseqs = str[i:j+1].pal_subseqs

        str::pal_subseqs_size_def: {str, i, j} => size
            size = str.pal_subseqs(i, j).size


    @算法
        str::first_inner_eq_id: {str, i, j} => id
            ∀
                |- ∃{ str[k] = str[i] | i < k < j }
                    id = min{ k | str[k] = str[i] | i < k < j }
                |- !∃{ str[k] = str[i] | i < k < j }
                    id = null

        str::last_inner_eq_id: {str, i, j} => id
            ∀
                |- ∃{ str[k] = str[i] | i < k < j }
                    id = max{ k | str[k] = str[i] | i < k < j }
                |- !∃{ str[k] = str[i] | i < k < j }
                    id = null

        str::pal_subseqs_size: {str, i, j} => size
            ∀
                |- i > j
                    size = 0
                |- i = j
                    size = 1
                |- i < j
                    |- str[i] ≠ str[j]
                        | v1 = str.pal_subseqs_size(i + 1, j)
                        | v2 = str.pal_subseqs_size(i, j - 1)
                        | v3 = str.pal_subseqs_size(i + 1, j - 1)
                        size = v1 + v2 - v3
                    |- str[i] = str[j]
                        | inner = str.pal_subseqs_size(i + 1, j - 1)
                        | left_id = str.first_inner_eq_id(i, j)
                        | right_id = str.last_inner_eq_id(i, j)
                        ∀
                            |- left_id = null
                                size = 2 * inner + 2
                            |- left_id = right_id
                                size = 2 * inner + 1
                            |- left_id < right_id
                                | dup = str.pal_subseqs_size(left_id + 1, right_id - 1)
                                size = 2 * inner - dup

        str::pal_subseqs_size: str => size
            size = str.pal_subseqs_size(0, str.size - 1)
