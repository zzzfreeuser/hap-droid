import graphviz

with open("out\\contacts\\2026-03-19-23-57-27\\ptg.dot") as f:
    dot_graph = f.read()
dot=graphviz.Source(dot_graph)
dot.view()
