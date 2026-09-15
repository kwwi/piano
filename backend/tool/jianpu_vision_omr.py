#!/usr/bin/env python3
"""DeepSeek Vision → 标准 ABC 记谱 → 单文件 HTML 预览（abcjs 渲染）。

用法示例::

    export DEEPSEEK_API_KEY=sk-...
    python tool/jianpu_vision_omr.py path/to/score.jpg --open

也可把 key 写在仓库根或 backend/ 下的 ``.env``::

    DEEPSEEK_API_KEY=sk-...
    # 可选：
    # DEEPSEEK_BASE_URL=https://api.deepseek.com
    # DEEPSEEK_VISION_MODEL=deepseek-v4-flash-vision-exp
"""
from __future__ import annotations

import argparse
import base64
import html
import json
import mimetypes
import os
import re
import sys
import webbrowser
from datetime import datetime, timezone
from pathlib import Path

try:
    import httpx
except ImportError:  # pragma: no cover
    print("需要 httpx：pip install httpx", file=sys.stderr)
    raise SystemExit(1)

DEFAULT_BASE_URL = "https://api.deepseek.com"
DEFAULT_MODEL = "deepseek-v4-flash-vision-exp"
ABCJS_CDN = "https://cdn.jsdelivr.net/npm/abcjs@6.4.4/dist/abcjs-basic-min.js"

PROMPT = """你是简谱（数字谱 / Jianpu）光学识别与记谱专家。任务：把图片中的**主旋律**准确转写为**标准 ABC 记谱法**（ABC Notation / abc standard）。

只识别主旋律，忽略：和弦圈/和弦名、指法数字、歌词、水印、段落标签旁注、装饰性连线旁文字。

==================== 输出格式（必须遵守） ====================
只输出一份合法 ABC 文本，不要 markdown 代码围栏，不要解释。

必须以这些字段开头（按需增减，但 X/T/M/L/K 必有）：
X:1
T:曲名（看不清则写 Unknown）
C:演唱或作者（可选，看不清可省略）
M:4/4
L:1/4
Q:1/4=100
K:Ab
（正文音符与小节）

示例（仅说明格式，勿照抄音高）：
X:1
T:Example
M:4/4
L:1/4
Q:1/4=90
K:C
z/2 A,/2 B,/2 | c3/2 B/2 c/2 d3/2 | e/2 f/2 g/4 a/4 b/4 c'/4 d'3/2 |

==================== 简谱 → ABC 对照（必须做对） ====================

【调号 K:】
- 简谱页眉「1=C / 1=G / 1=^bA / 1=bA / 1=Ab」等 → 写成标准 K:（如 K:C、K:G、K:Ab）。
- 音高用**绝对音名**写在该调下：简谱数字 1–7 是相对唱名，先按 K: 换算成 CDEFGAB（含升降）。

【八度（最容易错，务必逐音核对）】
- 简谱数字**上方**的圆点 = 高八度；**下方**的圆点 = 低八度；无点 = 中间八度。
- ABC 八度约定（以中央 C 附近为准）：
  - 低八度：C, D, E, F, G, A, B,   （字母后加逗号）
  - 中八度：C D E F G A B
  - 高八度：c d e f g a b
  - 再高：c' d' …
- 同一乐句内八度常变化（例如前奏先低后高），禁止整行默认同一八度。

【节奏 / 时值（必须与简谱记号一致）】
默认 L:1/4（四分音符为单位）：
- 无下划线的数字 ≈ 四分 → C
- 单下划线 ≈ 八分 → C/2
- 双下划线 ≈ 十六分 → C/4
- 三下划线 ≈ 三十二分 → C/8
- 右侧附点（时值×1.5）：四分附点 → C3/2；八分附点 → C3/4
- 简谱休止 0：按同样下划线规则写 z、z/2、z/4 …

【延音 / 长音 / 连音】
- 简谱音后的水平短横「- - -」是**延长时值**（同一音持续），优先写成更长时值：
  如 5 - - - 在 4/4 且 L:1/4 下 ≈ 全音符 → A4（或按实际拍数 A2 / A3）。
- 若两音相同且有连结线（tie），用 ABC 延音线：c-c 或 (c c)
- 不要把延音横线误认成新的音符。

【小节与结构】
- 竖线 | 分小节；行末可 | 或 |]
- 尽量让每小节拍数与 M: 一致；看不清可保留结构但不要乱补拍。
- 多行简谱按阅读顺序连续写入同一曲（可用 \\ 断行续写，或自然换行，ABC 允许）。

【质量自检（输出前默默检查）】
1. 每个带上下圆点的音，八度是否写对？
2. 每个下划线组，时值是否写成 /2 /4？
3. 每个「音 + 横线延音」，是否合并成长时值而不是多个四分？
4. K: 是否与页眉 1= 一致？
5. 是否只含主旋律（没有把和弦圈数字写进去）？

再次强调：只输出 ABC 正文，不要其它文字。
"""


def _repo_roots() -> list[Path]:
    here = Path(__file__).resolve()
    backend = here.parent.parent
    repo = backend.parent
    return [Path.cwd(), backend, repo]


def load_dotenv() -> None:
    """Load simple KEY=VALUE lines from .env (no dependency)."""
    for root in _repo_roots():
        env_path = root / ".env"
        if not env_path.is_file():
            continue
        for raw in env_path.read_text(encoding="utf-8").splitlines():
            line = raw.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, _, val = line.partition("=")
            key = key.strip()
            val = val.strip().strip("'").strip('"')
            if key and key not in os.environ:
                os.environ[key] = val
        break


def image_to_data_url(path: Path) -> tuple[str, bytes]:
    data = path.read_bytes()
    mime, _ = mimetypes.guess_type(path.name)
    if mime not in {"image/jpeg", "image/png", "image/gif", "image/webp"}:
        if data[:3] == b"\xff\xd8\xff":
            mime = "image/jpeg"
        elif data[:8] == b"\x89PNG\r\n\x1a\n":
            mime = "image/png"
        elif data[:4] == b"RIFF" and data[8:12] == b"WEBP":
            mime = "image/webp"
        elif data[:6] in (b"GIF87a", b"GIF89a"):
            mime = "image/gif"
        else:
            mime = "image/jpeg"
    b64 = base64.b64encode(data).decode("ascii")
    return f"data:{mime};base64,{b64}", data


def call_deepseek_vision(
    *,
    api_key: str,
    base_url: str,
    model: str,
    data_url: str,
    detail: str,
    timeout: float,
) -> str:
    url = base_url.rstrip("/") + "/chat/completions"
    payload = {
        "model": model,
        "messages": [
            {
                "role": "user",
                "content": [
                    {"type": "text", "text": PROMPT},
                    {
                        "type": "image_url",
                        "image_url": {"url": data_url, "detail": detail},
                    },
                ],
            }
        ],
        "temperature": 0.1,
    }
    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
    }
    with httpx.Client(timeout=timeout) as client:
        resp = client.post(url, headers=headers, json=payload)
        if resp.status_code >= 400:
            raise RuntimeError(
                f"DeepSeek API HTTP {resp.status_code}: {resp.text[:800]}"
            )
        body = resp.json()
    try:
        return str(body["choices"][0]["message"]["content"])
    except (KeyError, IndexError, TypeError) as exc:
        raise RuntimeError(f"意外响应：{json.dumps(body)[:800]}") from exc


def extract_abc(raw: str) -> str:
    """Strip markdown fences / chatter; keep ABC if present."""
    text = raw.strip()
    fence = re.search(r"```(?:abc|ABC)?\s*([\s\S]*?)```", text)
    if fence:
        text = fence.group(1).strip()
    # Prefer from first ABC header field
    m = re.search(r"(?m)^(?:X|T|M|L|K|Q|C|Z|N|B|D|F|G|H|I|O|P|R|S|W|w):\s*", text)
    if m:
        text = text[m.start() :].strip()
    return text


def build_html(
    *,
    image_path: Path,
    image_data_url: str,
    abc: str,
    raw_model: str,
    model: str,
) -> str:
    title = "简谱 → ABC"
    m = re.search(r"(?m)^T:\s*(.+)$", abc)
    if m:
        title = m.group(1).strip() or title
    # Embed as JSON string so JS gets exact ABC (escapes newlines etc.)
    abc_json = json.dumps(abc, ensure_ascii=False)
    safe_raw = html.escape(raw_model)
    safe_path = html.escape(str(image_path))
    safe_model = html.escape(model)
    generated = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")

    return f"""<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="utf-8"/>
<meta name="viewport" content="width=device-width, initial-scale=1"/>
<title>{html.escape(title)} — ABC / DeepSeek Vision</title>
<script src="{ABCJS_CDN}"></script>
<style>
  :root {{
    --bg: #f6f4ef;
    --card: #fffdf8;
    --ink: #1a1a1a;
    --muted: #666;
    --line: #e6e0d4;
    --accent: #2b6cb0;
  }}
  * {{ box-sizing: border-box; }}
  body {{
    margin: 0; font-family: "SF Pro Text", "PingFang SC", "Noto Sans SC",
      system-ui, sans-serif; background: var(--bg); color: var(--ink);
    line-height: 1.5;
  }}
  header {{
    padding: 20px 24px 8px; max-width: 1100px; margin: 0 auto;
  }}
  header h1 {{ margin: 0 0 6px; font-size: 1.35rem; font-weight: 650; }}
  header p {{ margin: 0; color: var(--muted); font-size: 0.9rem; }}
  main {{
    max-width: 1100px; margin: 0 auto; padding: 12px 24px 48px;
    display: grid; gap: 16px;
  }}
  .card {{
    background: var(--card); border: 1px solid var(--line); border-radius: 12px;
    padding: 16px 18px; box-shadow: 0 1px 2px rgba(0,0,0,.04);
  }}
  .card h2 {{
    margin: 0 0 12px; font-size: 0.95rem; letter-spacing: .02em;
    color: var(--accent); font-weight: 650;
  }}
  .grid2 {{
    display: grid; gap: 16px; grid-template-columns: 1fr;
  }}
  @media (min-width: 900px) {{
    .grid2 {{ grid-template-columns: 1fr 1fr; }}
  }}
  img.source {{
    width: 100%; height: auto; border-radius: 8px; border: 1px solid var(--line);
    background: #fff;
  }}
  pre.abc {{
    margin: 0; white-space: pre-wrap; word-break: break-word;
    font-family: ui-monospace, SFMono-Regular, Menlo, Consolas, monospace;
    font-size: 0.85rem; background: #f3f0ea; padding: 12px; border-radius: 8px;
    max-height: 420px; overflow: auto;
  }}
  #paper {{
    min-height: 120px; overflow-x: auto; padding: 8px 4px 16px; background: #fff;
    border-radius: 8px; border: 1px solid var(--line);
  }}
  #paper-error {{ color: #c53030; font-size: 0.9rem; margin-top: 8px; }}
  summary {{ cursor: pointer; color: var(--muted); font-size: 0.85rem; }}
</style>
</head>
<body>
<header>
  <h1>{html.escape(title)}</h1>
  <p>标准 ABC · 模型 <code>{safe_model}</code> · 源图 <code>{safe_path}</code> · {generated}</p>
</header>
<main>
  <div class="grid2">
    <section class="card">
      <h2>原图</h2>
      <img class="source" src="{image_data_url}" alt="source score"/>
    </section>
    <section class="card">
      <h2>ABC 文本</h2>
      <pre class="abc" id="abc-text"></pre>
      <details style="margin-top:10px">
        <summary>模型原始输出</summary>
        <pre class="abc">{safe_raw}</pre>
      </details>
    </section>
  </div>
  <section class="card">
    <h2>五线谱渲染（abcjs）</h2>
    <div id="paper"></div>
    <div id="paper-error"></div>
  </section>
</main>
<script>
(function () {{
  const abc = {abc_json};
  document.getElementById('abc-text').textContent = abc;
  const err = document.getElementById('paper-error');
  try {{
    if (typeof ABCJS === 'undefined' || !ABCJS.renderAbc) {{
      err.textContent = '未能加载 abcjs（需联网访问 CDN）。ABC 文本仍可复制使用。';
      return;
    }}
    ABCJS.renderAbc('paper', abc, {{
      responsive: 'resize',
      add_classes: true,
      paddingleft: 0,
      paddingright: 0,
    }});
  }} catch (e) {{
    err.textContent = 'ABC 渲染失败：' + (e && e.message ? e.message : e);
  }}
}})();
</script>
</body>
</html>
"""


def default_out_paths(image: Path) -> tuple[Path, Path]:
    stem = image.with_suffix("")
    return Path(f"{stem}.vision.abc"), Path(f"{stem}.vision.html")


def main(argv: list[str] | None = None) -> int:
    load_dotenv()
    parser = argparse.ArgumentParser(
        description="用 DeepSeek Vision 识别简谱图片，输出标准 ABC 与单文件 HTML 渲染。"
    )
    parser.add_argument("image", type=Path, help="简谱图片路径（jpg/png/webp/gif）")
    parser.add_argument(
        "-o",
        "--html-out",
        type=Path,
        default=None,
        help="HTML 输出路径（默认：<图片名>.vision.html）",
    )
    parser.add_argument(
        "--abc-out",
        type=Path,
        default=None,
        help="ABC 文本输出路径（默认：<图片名>.vision.abc）",
    )
    # backward-compatible alias
    parser.add_argument("--dsl-out", type=Path, default=None, help=argparse.SUPPRESS)
    parser.add_argument(
        "--api-key",
        default=os.environ.get("DEEPSEEK_API_KEY", ""),
        help="API Key（默认读环境变量 DEEPSEEK_API_KEY 或 .env）",
    )
    parser.add_argument(
        "--base-url",
        default=os.environ.get("DEEPSEEK_BASE_URL", DEFAULT_BASE_URL),
        help=f"API Base URL（默认 {DEFAULT_BASE_URL}）",
    )
    parser.add_argument(
        "--model",
        default=os.environ.get("DEEPSEEK_VISION_MODEL", DEFAULT_MODEL),
        help=f"模型名（默认 {DEFAULT_MODEL}）",
    )
    parser.add_argument(
        "--detail",
        choices=("low", "high", "original", "auto"),
        default=os.environ.get("DEEPSEEK_VISION_DETAIL", "high"),
        help="图像 detail（简谱建议 high/original）",
    )
    parser.add_argument(
        "--timeout",
        type=float,
        default=float(os.environ.get("DEEPSEEK_TIMEOUT", "180")),
        help="请求超时秒数",
    )
    parser.add_argument(
        "--open",
        action="store_true",
        help="完成后用系统浏览器打开 HTML",
    )
    args = parser.parse_args(argv)

    image: Path = args.image.expanduser().resolve()
    if not image.is_file():
        print(f"找不到图片：{image}", file=sys.stderr)
        return 2
    if not args.api_key:
        print(
            "未配置 API Key。请设置环境变量 DEEPSEEK_API_KEY，"
            "或在仓库根目录 / backend/ 创建 .env，或传 --api-key。",
            file=sys.stderr,
        )
        return 2

    abc_out, html_out = default_out_paths(image)
    if args.abc_out:
        abc_out = args.abc_out.expanduser().resolve()
    elif args.dsl_out:
        abc_out = args.dsl_out.expanduser().resolve()
    if args.html_out:
        html_out = args.html_out.expanduser().resolve()

    print(f"读取图片：{image}")
    data_url, _ = image_to_data_url(image)
    print(f"调用 {args.model} @ {args.base_url} …")
    raw = call_deepseek_vision(
        api_key=args.api_key,
        base_url=args.base_url,
        model=args.model,
        data_url=data_url,
        detail=args.detail,
        timeout=args.timeout,
    )
    abc = extract_abc(raw)
    abc_out.write_text(abc + "\n", encoding="utf-8")
    html_doc = build_html(
        image_path=image,
        image_data_url=data_url,
        abc=abc,
        raw_model=raw,
        model=args.model,
    )
    html_out.write_text(html_doc, encoding="utf-8")

    print("--- ABC ---")
    print(abc)
    print("-----------")
    print(f"已写入：{abc_out}")
    print(f"已写入：{html_out}")
    if args.open:
        webbrowser.open(html_out.as_uri())
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
