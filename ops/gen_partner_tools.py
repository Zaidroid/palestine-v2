"""Print PARTNER-API §3 from the server's own tools/list (audit F153): the
document used to teach the retired 28-tool surface. Paste the output over §3.

    .venv/bin/python -m ops.gen_partner_tools
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))


def main() -> int:
    from serve.mcp_facades import listed_tools
    print("## 3. The tools\n")
    print("Sixteen public names, generated from the server's own `tools/list` "
          "(`ops/gen_partner_tools.py`; a required argument is starred, a declared "
          "default is shown). Older names still answer for one release but are not "
          "on the menu.\n")
    for t in listed_tools():
        props = t["inputSchema"].get("properties", {})
        req = set(t["inputSchema"].get("required", []))
        args = ", ".join(f"`{k}`" + ("*" if k in req else "")
                         + (f"={json.dumps(v.get('default'), ensure_ascii=False)}"
                            if v.get("default") is not None else "")
                         for k, v in props.items()) or "no arguments"
        print(f"**`{t['name']}`** — {t['description']}\n  <br>arguments: {args}\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
