# test1
source = 
"
val ~ min_val
∀{| val1 | val1 ≥ min_val}
"
disassemble(compile(source)) = 
"
∀{
val ~ min_val
∀{
  | val1
  | sym ~ val1
  | val1 ~ val1
  | val ~ val1
  val1 ≥ min_val
  }
}
"

