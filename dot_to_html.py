from pathlib import Path
import json

def dot_to_html(dot_file: Path, output_html: Path = None) -> None:
    """
    将 .dot 文件转换为 HTML 网页（d3-graphviz 渲染）
    """
    if output_html is None:
        output_html = dot_file.parent / dot_file.stem / "ptg.html"
    
    dot_content = dot_file.read_text(encoding="utf-8", errors="ignore")
    
    html = f"""<!doctype html>
<html lang="zh-CN">
<head>
  <meta charset="utf-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1" />
  <title>PTG 可视化</title>
  <style>
    * {{ margin: 0; padding: 0; }}
    body {{ 
      font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Arial, sans-serif;
      background: #f5f5f5;
    }}
    #toolbar {{ 
      padding: 15px 20px; 
      background: white;
      border-bottom: 1px solid #e0e0e0;
      box-shadow: 0 2px 4px rgba(0,0,0,0.05);
      display: flex;
      justify-content: space-between;
      align-items: center;
    }}
    #toolbar h2 {{ font-size: 18px; color: #333; }}
    #toolbar small {{ color: #999; }}
    #graph {{ 
      width: 100vw; 
      height: calc(100vh - 60px);
      overflow: auto;
      background: white;
    }}
    svg {{ 
      background: white;
      display: block;
    }}
  </style>
</head>
<body>
  <div id="toolbar">
    <div>
      <h2>HapTest PTG 可视化</h2>
      <small>支持鼠标缩放、拖拽、悬停查看详情</small>
    </div>
  </div>
  <div id="graph"></div>
  
  <script src="https://unpkg.com/d3@7"></script>
  <script src="https://unpkg.com/@hpcc-js/wasm@2.16.2/dist/index.min.js"></script>
  <script src="https://unpkg.com/d3-graphviz@5.1.0/build/d3-graphviz.min.js"></script>
  
  <script>
    const dot = {json.dumps(dot_content)};
    
    d3.select("#graph")
      .graphviz()
      .zoom(true)
      .fit(true)
      .renderDot(dot);
  </script>
</body>
</html>"""

    output_html.parent.mkdir(parents=True, exist_ok=True)
    output_html.write_text(html, encoding="utf-8")
    print(f"✓ HTML generated: {output_html}")


if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument("dot_file", type=Path, help="输入 .dot 文件")
    parser.add_argument("-o", "--output", type=Path, help="输出 HTML 文件（默认同名）")
    args = parser.parse_args()
    
    dot_to_html(args.dot_file, args.output)