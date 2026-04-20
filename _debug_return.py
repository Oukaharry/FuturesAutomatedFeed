"""Debug why place_buy_order returns None"""
import ast

with open(r'trader_companion/topstepx.py', 'r', encoding='utf-8') as f:
    source = f.read()

tree = ast.parse(source)

for node in ast.walk(tree):
    if isinstance(node, ast.FunctionDef) and node.name == 'place_buy_order':
        print(f"Function at line {node.lineno}")
        print(f"Number of top-level statements in body: {len(node.body)}")
        
        for i, stmt in enumerate(node.body):
            print(f"  Body[{i}]: {type(stmt).__name__} at line {stmt.lineno}")
            
            if isinstance(stmt, ast.With):
                print(f"    With body has {len(stmt.body)} statements")
                for j, ws in enumerate(stmt.body):
                    print(f"    With[{j}]: {type(ws).__name__} at line {ws.lineno}")
                    
                    if isinstance(ws, ast.Try):
                        print(f"      Try body has {len(ws.body)} statements")
                        # Print all returns in the try body
                        for k, ts in enumerate(ws.body):
                            if isinstance(ts, ast.Return):
                                print(f"      RETURN in try body at line {ts.lineno}")
                            elif isinstance(ts, ast.If):
                                # Check if blocks for returns
                                for ifs in ast.walk(ts):
                                    if isinstance(ifs, ast.Return):
                                        print(f"      RETURN in if-block at line {ifs.lineno}")
                            elif isinstance(ts, ast.Try):
                                print(f"      Inner Try at line {ts.lineno}")
                        
                        for handler in ws.handlers:
                            print(f"      Handler at line {handler.lineno}")
                            for hs in handler.body:
                                if isinstance(hs, ast.Return):
                                    print(f"        RETURN in handler at line {hs.lineno}")

        # Count all Return nodes
        returns = [n for n in ast.walk(node) if isinstance(n, ast.Return)]
        print(f"\nTotal Return statements: {len(returns)}")
        for r in returns:
            print(f"  Return at line {r.lineno}")
