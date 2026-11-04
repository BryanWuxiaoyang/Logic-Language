# Runnable examples

[Project README](../README.md) | [中文](#chinese)

Run these commands from the project root after installing `requirements.txt`:

```sh
python examples/check_examples.py
```

Expected output:

```text
Checked 7 LP files: 0 errors, 0 warnings.
Program correspondence checks passed (finite cases, not a formal proof).
```

The checker validates each `.lp` file and examines representative programs against membership, conditional guarantees, and counterexamples. The Python files are illustrative implementations with documented interpretations, not compiler-generated code. Run any demo directly:

| Example | Command | Output |
| --- | --- | --- |
| Computation and several contracts | `python examples/contracts/quadruple.py` | `[-8, 0, 12]` |
| Minimum of a nonempty integer set | `python examples/algorithms/minimum.py` | `-2` |
| Active adult user IDs | `python examples/data_processing/eligible_ids.py` | `[1]` |
| Ownership or shared access | `python examples/access_control/can_read.py` | `[True, True, False]` |
| Class fields and a method | `python examples/classes/point.py` | `5` |
| Function properties | `python examples/learning/function_properties.py` | `False`, `True`, `False`, `True`, each on its own line |

## Interpretations and boundaries

- **Contracts:** `Value` denotes integers. The quadruple contract specifies computation dependencies, sign guarantees, and order preservation; multiplication is one implementation.
- **Minimum:** the input is a finite, nonempty integer set. Membership and the order condition characterize the result. Raising `ValueError` on empty input is an implementation decision outside the contract's domain.
- **User IDs:** input records have integer `age`, Boolean `active`, and hashable `id` fields. `active`, `age`, and `user_id` read those fields. Output is a set. Sorting in the demo is only for display. Missing or malformed fields are outside this example's model.
- **Access:** `is_owner(user, document)` compares the user with `document["owner"]`; `shared_with(document, user)` tests membership in `document["shared"]`. The equation covers all four combinations of these conditions.
- **Classes:** `Point` objects have integer coordinates. LP field access denotes a unary function of the receiver, and `shifted_x` is a binary function of the point and delta. The Python method returns the computed coordinate while preserving the source point. LP does not specify the Python constructor or storage layout.
- **Learning:** domains and codomains are finite integer sets, and the function is integer-valued. Mapping, injectivity, and surjectivity are defined properties, not claims that all functions satisfy them. Surjectivity alone checks codomain coverage; combine it with the mapping condition when examining a function from a specified domain to a specified codomain.

For the square function, `1` and `−1` witness failure of injectivity. Restricting to `{0, 1, 2}` makes it injective, but it is not surjective onto `{0, 1, 2, 3, 4}`. Its image `{0, 1, 4}` gives a codomain onto which it is surjective. These finite demonstrations do not prove statements about infinite domains.

Keep definitions, model assumptions, conjectures, and established results separate when extending the learning example. Record sources and explanations in comments or accompanying prose; the compiler does not verify proof status.

Inspect one compiled example:

```sh
python scripts/module_check.py --file examples/data_processing/eligible_ids.lp --pretty
python scripts/expand_module.py examples/data_processing/eligible_ids.lp
```

<a id="chinese"></a>

<details>
<summary>中文说明 / Read in Chinese</summary>

安装 `requirements.txt` 后，从项目根目录执行：

```sh
python examples/check_examples.py
```

预期输出：

```text
Checked 7 LP files: 0 errors, 0 warnings.
Program correspondence checks passed (finite cases, not a formal proof).
```

检查器验证每个 `.lp` 文件，并通过成员条件、条件保证和反例检查代表性程序。Python 文件是具有明确解释的示范实现，并非编译器生成的代码。可以直接运行各个演示：

| 示例 | 命令 | 输出 |
| --- | --- | --- |
| 计算依赖与多组契约 | `python examples/contracts/quadruple.py` | `[-8, 0, 12]` |
| 非空整数集合的最小值 | `python examples/algorithms/minimum.py` | `-2` |
| 成年活跃用户 ID | `python examples/data_processing/eligible_ids.py` | `[1]` |
| 所有者或共享权限 | `python examples/access_control/can_read.py` | `[True, True, False]` |
| 类字段与方法 | `python examples/classes/point.py` | `5` |
| 函数性质 | `python examples/learning/function_properties.py` | 依次输出 `False`、`True`、`False`、`True`，每项一行 |

## 解释与边界

- **契约：**`Value` 表示整数。四倍函数规定计算依赖、符号保证和顺序保持，乘法是一种实现。
- **最小值：**输入为有限、非空整数集合。成员条件和顺序条件刻画结果。空输入时抛出 `ValueError` 是契约适用域之外的实现选择。
- **用户 ID：**记录具有整数 `age`、布尔值 `active` 和可哈希 `id` 字段，`active`、`age` 与 `user_id` 读取相应字段。输出是集合，演示排序仅用于显示。缺失或格式错误的字段不在本例模型内。
- **权限：**`is_owner(user, document)` 比较用户与 `document["owner"]`；`shared_with(document, user)` 判断用户是否属于 `document["shared"]`。等式覆盖两个条件的四种组合。
- **类：**`Point` 对象具有整数坐标。LP 字段访问表示接收者上的一元函数，`shifted_x` 表示以点和偏移量为参数的二元函数。Python 方法返回计算得到的坐标，并保持源点的数据。LP 不规定 Python 构造器或存储布局。
- **学习：**定义域与陪域是有限整数集合，函数返回整数。映射、单射和满射是被定义的性质，不是所有函数均满足它们的断言。满射检查陪域覆盖；研究指定定义域到指定陪域的函数时，应同时检查映射条件。

平方函数的 `1` 与 `−1` 构成不满足单射的见证。限制到 `{0, 1, 2}` 后，它是单射，但不是到 `{0, 1, 2, 3, 4}` 的满射。取像集 `{0, 1, 4}` 为陪域，它就是满射。这些有限演示不证明无限输入域上的结论。

扩展学习示例时，应区分定义、模型假设、猜想和已确立结论。通过注释或配套文字记录来源与解释，编译器不验证证明状态。

查看单个示例的编译结果：

```sh
python scripts/module_check.py --file examples/data_processing/eligible_ids.lp --pretty
python scripts/expand_module.py examples/data_processing/eligible_ids.lp
```

</details>
