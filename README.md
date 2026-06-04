# Harzoo

Harzoo is a simple, flexible, powerful Python AI agent framework. 

Just 1300 lines of code. 

It is a universal world‑task architecture: `s₀ → [LLM + tools] → s₁ → [LLM + tools] → s₂ → …`

## Documentation

```text
www.harzoo.com
```

## Repository Layout


| Path      | Purpose                              |
| --------- | ------------------------------------ |
| `src/`    | code                                 |
| `docs/`   | Documentation, official config files |
| `assets/` | Official config files |
| `other`   | Project management                   |


## Quick Start

1. **Install**
   ```bash
   pip install harzoo
   ```
2. **Run**

   Opens the terminal UI. On first run, Harzoo creates a config folder:

   ```bash
   harzoo
   ```
3. **Configure**

   Edit files under:

   ```text
   ~/.harzoo/config/
   ```

   - Copy files from `assets/config/` into the folder above, and update API settings (`api_key`, `base_url`, `model_name`) in your profile.
   - Update `config.json` — set `startup_profile` to your profile file.

4. **Restart**

   Quit Harzoo and run again to load your changes:

   ```bash
   harzoo
   ```

## Python Examples

### High-level

```python
from harzoo import start
from harzoo.agent.kernel.message import user_message

config_dir = "~/.harzoo/config"
queue_in, queue_out = start(config_dir)

user_message = user_message([{"type": "text", "text": "Hello"}])
queue_in.put(user_message)

print(queue_out.get())
```

### Low-level

```python
from harzoo import Agent
from harzoo.agent.components.paths import prepare_config_paths
from harzoo.agent.kernel.message import assistant_message, tool_message, user_message
from harzoo.agent.kernel.tool import Context

paths = prepare_config_paths("~/.harzoo/config")
agent = Agent.from_profile(paths.startup_profile_path, paths)

state = []

user_message = user_message([{"type": "text", "text": "Hello"}])
state.append(user_message)

while state and state[-1].get("role") in ("user", "tool"):
    ctx = Context(state=state, agent=agent, config_paths=paths)
    content, tool_calls, _ = agent.decide(state)
    state.append(assistant_message(content=content, tool_calls=tool_calls))
    if tool_calls:
        for tc in tool_calls:
            fn = tc["function"]
            result = agent.execute_tool_call(str(fn["name"]), str(fn["arguments"]), ctx)
            tool_message = tool_message(str(tc["id"]), result)
            state.append(tool_message)

print(state[-1])
```

## License

MIT