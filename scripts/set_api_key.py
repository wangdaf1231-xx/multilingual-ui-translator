# -*- coding: utf-8 -*-
"""在终端写入 DEEPSEEK_API_KEY 到项目 .env（不要把 key 发到聊天里）。"""
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
ENV = ROOT / ".env"
EXAMPLE = ROOT / ".env.example"


def main() -> None:
    if not ENV.exists():
        if EXAMPLE.exists():
            ENV.write_text(EXAMPLE.read_text(encoding="utf-8"), encoding="utf-8")
        else:
            ENV.write_text(
                "DEEPSEEK_API_KEY=\n"
                "DEEPSEEK_BASE_URL=https://api.deepseek.com\n"
                "DEEPSEEK_MODEL=deepseek-chat\n",
                encoding="utf-8",
            )
    print("请输入 DEEPSEEK_API_KEY 后回车（只写入本地 .env，不要发到对话）：")
    key = input().strip()
    if not key:
        print("未输入，已取消。")
        raise SystemExit(1)
    lines = ENV.read_text(encoding="utf-8").splitlines()
    found = False
    out = []
    for line in lines:
        if line.startswith("DEEPSEEK_API_KEY="):
            out.append("DEEPSEEK_API_KEY=" + key)
            found = True
        else:
            out.append(line)
    if not found:
        out.append("DEEPSEEK_API_KEY=" + key)
    ENV.write_text("\n".join(out) + "\n", encoding="utf-8")
    print("已写入 .env，重启服务后生效。")


if __name__ == "__main__":
    main()
