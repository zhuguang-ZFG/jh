"""Extract code patterns from source content using AST (Python) and regex (JS/TS/Rust/Go).

Returns list of {name, domain, description, code_example, confidence}.
"""
import re
import ast
import logging
from typing import List, Dict

logger = logging.getLogger("evo.pattern_extractor")


def extract_patterns(content: str, language: str, filepath: str) -> List[Dict]:
    """Extract code patterns from source content."""
    if not content or len(content.strip()) < 20:
        return []

    try:
        if language == "python":
            return _extract_python(content, filepath)
        elif language in ("javascript", "typescript"):
            return _extract_js_ts(content, language, filepath)
        elif language == "rust":
            return _extract_rust(content, filepath)
        elif language == "go":
            return _extract_go(content, filepath)
    except Exception as e:
        logger.debug(f"Pattern extraction failed ({language}): {e}")

    return []


def _extract_python(content: str, filepath: str) -> List[Dict]:
    """Python extraction using ast module."""
    patterns = []
    try:
        tree = ast.parse(content)
    except SyntaxError:
        # Partial parse: try line-by-line
        return _extract_python_regex(content, filepath)

    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            patterns.append(_python_func(node, filepath))
        elif isinstance(node, ast.ClassDef):
            patterns.append(_python_class(node, filepath))

    # Detect API routes from decorators
    patterns.extend(_detect_fastapi_routes(tree, filepath))

    return [p for p in patterns if p]


def _python_func(node, filepath: str) -> Dict:
    """Extract function pattern from AST node."""
    name = node.name
    is_async = isinstance(node, ast.AsyncFunctionDef)

    # Build signature
    args = []
    for arg in node.args.args:
        arg_str = arg.arg
        if arg.annotation:
            arg_str += f": {ast.unparse(arg.annotation)}"
        args.append(arg_str)
    sig = f"{'async ' if is_async else ''}def {name}({', '.join(args)})"

    # Return type
    if node.returns:
        sig += f" -> {ast.unparse(node.returns)}"

    # Docstring
    doc = ""
    if (node.body and isinstance(node.body[0], ast.Expr) and
            isinstance(node.body[0].value, (ast.Constant, ast.Str))):
        doc = node.body[0].value.value if isinstance(node.body[0].value, ast.Constant) else node.body[0].value.s
        if isinstance(doc, str):
            doc = doc.strip().split("\n")[0][:100]
        else:
            doc = ""

    # Code example: signature + first 3 lines of body
    body_lines = []
    for stmt in node.body[:3]:
        try:
            body_lines.append("    " + ast.unparse(stmt)[:100])
        except Exception:
            pass
    code_example = sig + ":\n" + "\n".join(body_lines) if body_lines else sig

    # Domain detection
    domain = _domain_from_path(filepath)
    decorators = [ast.unparse(d) for d in node.decorator_list]
    for d in decorators:
        if any(k in d for k in ("app.get", "app.post", "router.get", "router.post",
                                 "app.put", "app.delete", "router.put", "router.delete")):
            domain = "api"
            break
        if "pytest" in d or "fixture" in d or name.startswith("test_"):
            domain = "testing"
            break

    description = f"{'Async f' if is_async else 'F'}unction {name}()"
    if doc:
        description += f": {doc}"

    return {
        "name": f"func_{name}",
        "domain": domain,
        "description": description[:200],
        "code_example": code_example[:300],
        "confidence": 0.6,
    }


def _python_class(node, filepath: str) -> Dict:
    """Extract class pattern from AST node."""
    name = node.name
    bases = [ast.unparse(b) for b in node.bases]

    # Methods
    methods = []
    for item in node.body:
        if isinstance(item, (ast.FunctionDef, ast.AsyncFunctionDef)):
            methods.append(item.name)

    method_str = ", ".join(methods[:5]) if methods else "no methods"
    description = f"Class {name}"
    if bases:
        description += f"({', '.join(bases)})"
    description += f" with methods: {method_str}"

    # Code example: class def + first method signature
    code_lines = [f"class {name}:"]
    if bases:
        code_lines = [f"class {name}({', '.join(bases)}):"]
    for item in node.body[:2]:
        if isinstance(item, (ast.FunctionDef, ast.AsyncFunctionDef)):
            code_lines.append(f"    def {item.name}(...)")
    code_example = "\n".join(code_lines)[:300]

    domain = _domain_from_path(filepath)

    return {
        "name": f"class_{name.lower()}",
        "domain": domain,
        "description": description[:200],
        "code_example": code_example,
        "confidence": 0.5,
    }


def _detect_fastapi_routes(tree, filepath: str) -> List[Dict]:
    """Detect FastAPI/Flask route decorators."""
    routes = []
    for node in ast.walk(tree):
        if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            continue
        for dec in node.decorator_list:
            dec_str = ast.unparse(dec)
            m = re.search(r'\.(get|post|put|delete|patch)\s*\(\s*["\']([^"\']+)["\']', dec_str)
            if m:
                method, path = m.group(1).upper(), m.group(2)
                code_example = f"@app.{method.lower()}('{path}')\n{'async ' if isinstance(node, ast.AsyncFunctionDef) else ''}def {node.name}(...)"
                routes.append({
                    "name": f"route_{method.lower()}_{path.replace('/', '_').strip('_')}",
                    "domain": "api",
                    "description": f"API route: {method} {path}",
                    "code_example": code_example[:300],
                    "confidence": 0.7,
                })
    return routes


def _extract_python_regex(content: str, filepath: str) -> List[Dict]:
    """Regex fallback for Python when AST parse fails."""
    patterns = []
    lines = content.split("\n")

    for i, line in enumerate(lines):
        m = re.match(r"^(?:async\s+)?def\s+(\w+)\s*\(([^)]*)\)", line)
        if m:
            func_name, args = m.group(1), m.group(2)
            body = "\n".join(lines[i:i+4])[:200]
            patterns.append({
                "name": f"func_{func_name}",
                "domain": _domain_from_path(filepath),
                "description": f"Function {func_name}({args[:60]})",
                "code_example": body,
                "confidence": 0.5,
            })

        m = re.match(r"^class\s+(\w+)(?:\(([^)]*)\))?", line)
        if m:
            cls_name = m.group(1)
            body = "\n".join(lines[i:i+4])[:200]
            patterns.append({
                "name": f"class_{cls_name.lower()}",
                "domain": _domain_from_path(filepath),
                "description": f"Class {cls_name}",
                "code_example": body,
                "confidence": 0.5,
            })

    return patterns


# ─── JS/TS ───────────────────────────────────────────────────────────────────

_JS_TS_FUNC_PATTERNS = [
    # function declaration: function name(...)
    (r'(?:export\s+)?(?:async\s+)?function\s+(\w+)\s*\(([^)]*)\)', "function"),
    # arrow function: const/let name = (...) =>
    (r'(?:export\s+)?(?:const|let)\s+(\w+)\s*=\s*(?:async\s+)?\(([^)]*)\)\s*=>', "arrow"),
    # arrow function: const/let name = async (...) =>
    (r'(?:export\s+)?(?:const|let)\s+(\w+)\s*=\s*(?:async\s+)?function\s*\(([^)]*)\)', "function_expr"),
    # method in class: name(...) {
    (r'^\s+(?:async\s+)?(\w+)\s*\(([^)]*)\)\s*\{', "method"),
]

_JS_TS_CLASS_PATTERN = r'(?:export\s+)?(?:abstract\s+)?class\s+(\w+)(?:\s+extends\s+(\w+))?(?:\s+implements\s+([\w,\s]+))?'

_TS_INTERFACE_PATTERN = r'(?:export\s+)?interface\s+(\w+)(?:\s+extends\s+([\w,\s]+))?\s*\{'

_TS_TYPE_PATTERN = r'(?:export\s+)?type\s+(\w+)\s*='


def _extract_js_ts(content: str, language: str, filepath: str) -> List[Dict]:
    """JS/TS extraction using enhanced regex."""
    patterns = []
    lines = content.split("\n")

    for i, line in enumerate(lines):
        # Functions
        for regex, kind in _JS_TS_FUNC_PATTERNS:
            m = re.search(regex, line)
            if m:
                name, args = m.group(1), m.group(2)
                body = "\n".join(lines[i:i+4])[:200]
                is_export = "export" in line
                desc = f"{'Exported ' if is_export else ''}{kind} {name}({args[:60]})"
                patterns.append({
                    "name": f"js_{name}",
                    "domain": _domain_from_path(filepath),
                    "description": desc[:200],
                    "code_example": body,
                    "confidence": 0.5 if kind == "method" else 0.6,
                })

        # Classes
        m = re.search(_JS_TS_CLASS_PATTERN, line)
        if m:
            cls_name = m.group(1)
            extends = m.group(2) or ""
            body = "\n".join(lines[i:i+5])[:200]
            desc = f"Class {cls_name}"
            if extends:
                desc += f" extends {extends}"
            patterns.append({
                "name": f"class_{cls_name.lower()}",
                "domain": _domain_from_path(filepath),
                "description": desc[:200],
                "code_example": body,
                "confidence": 0.5,
            })

        # TS interfaces
        if language == "typescript":
            m = re.search(_TS_INTERFACE_PATTERN, line)
            if m:
                iface_name = m.group(1)
                body = "\n".join(lines[i:i+5])[:200]
                patterns.append({
                    "name": f"interface_{iface_name.lower()}",
                    "domain": _domain_from_path(filepath),
                    "description": f"Interface {iface_name}",
                    "code_example": body,
                    "confidence": 0.5,
                })

            m = re.search(_TS_TYPE_PATTERN, line)
            if m:
                type_name = m.group(1)
                patterns.append({
                    "name": f"type_{type_name.lower()}",
                    "domain": _domain_from_path(filepath),
                    "description": f"Type alias {type_name}",
                    "code_example": line.strip()[:200],
                    "confidence": 0.4,
                })

        # React components (function components)
        m = re.search(r'(?:export\s+(?:default\s+)?)?function\s+(\w+)\s*\((?:\{[^}]*\}|props)', line)
        if m:
            comp_name = m.group(1)
            if comp_name[0].isupper():  # React components start with uppercase
                patterns.append({
                    "name": f"component_{comp_name.lower()}",
                    "domain": "frontend",
                    "description": f"React component {comp_name}",
                    "code_example": "\n".join(lines[i:i+5])[:200],
                    "confidence": 0.6,
                })

    return patterns


# ─── Rust ────────────────────────────────────────────────────────────────────

_RUST_PATTERNS = [
    # fn / async fn
    (r'(?:pub\s+)?(?:async\s+)?fn\s+(\w+)(?:<[^>]*>)?\s*\(([^)]*)\)(?:\s*->\s*([^\s{]+))?', "func"),
    # struct
    (r'(?:pub\s+)?struct\s+(\w+)(?:<[^>]*>)?\s*\{?', "struct"),
    # enum
    (r'(?:pub\s+)?enum\s+(\w+)(?:<[^>]*>)?\s*\{?', "enum"),
    # trait
    (r'(?:pub\s+)?trait\s+(\w+)(?:<[^>]*>)?', "trait"),
    # impl Trait for Type
    (r'impl\s+(?:<[^>]*>\s+)?(\w+)\s+for\s+(\w+)', "impl_for"),
    # impl Type
    (r'impl\s+(?:<[^>]*>\s+)?(\w+)\s*\{?', "impl"),
]


def _extract_rust(content: str, filepath: str) -> List[Dict]:
    """Rust extraction using regex."""
    patterns = []
    lines = content.split("\n")

    for i, line in enumerate(lines):
        stripped = line.strip()
        if stripped.startswith("//"):
            continue

        for regex, kind in _RUST_PATTERNS:
            m = re.search(regex, stripped)
            if m:
                name = m.group(1)
                body = "\n".join(lines[i:i+4])[:200]

                if kind == "func":
                    args = m.group(2) or ""
                    ret = m.group(3) or ""
                    desc = f"fn {name}({args[:60]})"
                    if ret:
                        desc += f" -> {ret}"
                    patterns.append({
                        "name": f"fn_{name}",
                        "domain": _domain_from_path(filepath),
                        "description": desc[:200],
                        "code_example": body,
                        "confidence": 0.6,
                    })
                elif kind in ("struct", "enum", "trait"):
                    patterns.append({
                        "name": f"{kind}_{name.lower()}",
                        "domain": _domain_from_path(filepath),
                        "description": f"{kind.capitalize()} {name}",
                        "code_example": body,
                        "confidence": 0.5,
                    })
                elif kind == "impl_for":
                    trait_name = m.group(1)
                    type_name = m.group(2)
                    patterns.append({
                        "name": f"impl_{trait_name.lower()}_for_{type_name.lower()}",
                        "domain": _domain_from_path(filepath),
                        "description": f"impl {trait_name} for {type_name}",
                        "code_example": body,
                        "confidence": 0.6,
                    })
                elif kind == "impl":
                    patterns.append({
                        "name": f"impl_{name.lower()}",
                        "domain": _domain_from_path(filepath),
                        "description": f"impl {name}",
                        "code_example": body,
                        "confidence": 0.5,
                    })

    return patterns


# ─── Go ──────────────────────────────────────────────────────────────────────

_GO_PATTERNS = [
    # func (receiver) Name(...) ... {
    (r'func\s+\((\w+)\s+\*?(\w+)\)\s+(\w+)\s*\(([^)]*)\)', "method"),
    # func Name(...) ... {
    (r'func\s+(\w+)\s*\(([^)]*)\)', "func"),
    # type Name struct {
    (r'type\s+(\w+)\s+struct\s*\{', "struct"),
    # type Name interface {
    (r'type\s+(\w+)\s+interface\s*\{', "interface"),
]


def _extract_go(content: str, filepath: str) -> List[Dict]:
    """Go extraction using regex."""
    patterns = []
    lines = content.split("\n")

    for i, line in enumerate(lines):
        stripped = line.strip()
        if stripped.startswith("//"):
            continue

        for regex, kind in _GO_PATTERNS:
            m = re.search(regex, stripped)
            if m:
                body = "\n".join(lines[i:i+4])[:200]

                if kind == "method":
                    receiver_type = m.group(2)
                    method_name = m.group(3)
                    args = m.group(4) or ""
                    patterns.append({
                        "name": f"method_{receiver_type.lower()}_{method_name}",
                        "domain": _domain_from_path(filepath),
                        "description": f"({receiver_type}) {method_name}({args[:60]})",
                        "code_example": body,
                        "confidence": 0.6,
                    })
                elif kind == "func":
                    func_name = m.group(1)
                    args = m.group(2) or ""
                    patterns.append({
                        "name": f"func_{func_name}",
                        "domain": _domain_from_path(filepath),
                        "description": f"func {func_name}({args[:60]})",
                        "code_example": body,
                        "confidence": 0.6,
                    })
                elif kind in ("struct", "interface"):
                    type_name = m.group(1)
                    patterns.append({
                        "name": f"{kind}_{type_name.lower()}",
                        "domain": _domain_from_path(filepath),
                        "description": f"type {type_name} {kind}",
                        "code_example": body,
                        "confidence": 0.5,
                    })

    return patterns


# ─── Utilities ───────────────────────────────────────────────────────────────

def _domain_from_path(filepath: str) -> str:
    """Detect domain from file path."""
    fp = filepath.lower()
    if any(k in fp for k in ("test", "spec", "_test.py", ".test.")):
        return "testing"
    if any(k in fp for k in ("api", "route", "handler", "endpoint")):
        return "api"
    if any(k in fp for k in ("model", "schema", "db", "database", "migration")):
        return "data"
    if any(k in fp for k in ("config", "deploy", "ci", "docker", "makefile")):
        return "devops"
    if any(k in fp for k in ("hook", "evo")):
        return "python"
    if any(k in fp for k in ("component", "page", "view", "ui")):
        return "frontend"
    return "general"
