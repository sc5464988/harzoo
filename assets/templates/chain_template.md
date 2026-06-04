```text
State 1 (用户指令："分析 src/ 代码复杂度")
|
V
LLM 1 (决策：调用 Glob 锁定目标文件)
|
V
Tool 1: Glob (执行：匹配 src/ 下所有 .py 文件路径)
|
V
State 2 (获取结果：文件路径列表)
|
V
LLM 2 (决策：调用 Read 读取源码内容)
|
V
Tool 2: Read (执行：读取路径列表对应的文件内容)
|
V
State 3 (获取结果：源代码内容 + 原始指令)
|
V
...
```
