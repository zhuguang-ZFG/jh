"""Pattern extraction from source code — language-aware AST-lite scanning."""
import re
import hashlib


def extract_patterns(content: str, language: str, filepath: str) -> list[dict]:
    """Extract code patterns from source content."""
    patterns = []
    lines = content.split("\n")

    if language == "python":
        patterns.extend(_extract_python_patterns(lines, filepath))
    elif language in ("typescript", "javascript", "tsx"):
        patterns.extend(_extract_js_patterns(lines, filepath))
    elif language == "rust":
        patterns.extend(_extract_rust_patterns(lines, filepath))
    elif language == "go":
        patterns.extend(_extract_go_patterns(lines, filepath))

    return patterns


def _extract_python_patterns(lines: list[str], filepath: str) -> list[dict]:
    patterns = []
    domain = _infer_domain(filepath)

    # Decorator patterns
    for i, line in enumerate(lines):
        stripped = line.strip()
        if stripped.startswith("@") and "(" in stripped:
            decorator = stripped.split("(")[0].lstrip("@")
            if decorator in ("app.get", "app.post", "router.get", "router.post",
                             "router.middleware", "app.middleware"):
                context = "\n".join(lines[max(0, i - 1):min(len(lines), i + 3)])
                patterns.append({
                    "name": f"route_decorator_{decorator.split('.')[-1]}",
                    "domain": domain,
                    "description": f"Route pattern using {stripped}",
                    "code_example": context[:200],
                    "confidence": 0.6,
                })

    # Error handling patterns
    error_pattern = re.compile(r"(try|except|raise|assert)")
    has_error_handling = any(error_pattern.search(l) for l in lines)
    if has_error_handling:
        patterns.append({
            "name": "error_handling_pattern",
            "domain": domain,
            "description": f"Error handling in {filepath}",
            "code_example": "",
            "confidence": 0.4,
        })

    # Class definition patterns
    class_pattern = re.compile(r"^class\s+(\w+)")
    for i, line in enumerate(lines):
        m = class_pattern.match(line.strip())
        if m:
            class_name = m.group(1)
            # Get methods
            methods = [l.strip().split("(")[0] for l in lines[i+1:i+20]
                       if l.strip().startswith("def ") and not l.strip().startswith("def __")]
            if methods:
                patterns.append({
                    "name": f"class_{class_name.lower()}_pattern",
                    "domain": domain,
                    "description": f"Class {class_name} with methods: {', '.join(methods[:5])}",
                    "code_example": "",
                    "confidence": 0.5,
                })

    # Import patterns (dependency usage)
    import_pattern = re.compile(r"^(?:from\s+\S+\s+)?import\s+(\S+)")
    imports = set()
    for line in lines:
        m = import_pattern.match(line.strip())
        if m:
            imports.add(m.group(1))
    if imports:
        patterns.append({
            "name": f"imports_{'_'.join(sorted(imports)[:3])}",
            "domain": domain,
            "description": f"Dependency imports: {', '.join(sorted(imports)[:10])}",
            "code_example": "",
            "confidence": 0.3,
        })

    return patterns


def _extract_js_patterns(lines: list[str], filepath: str) -> list[dict]:
    patterns = []
    domain = _infer_domain(filepath)

    for i, line in enumerate(lines):
        stripped = line.strip()

        # React component pattern
        if re.match(r"(export\s+default\s+)?(function|const)\s+\w+.*=>", stripped):
            if "tsx" in filepath or "jsx" in filepath or "React" in "\n".join(lines[max(0, i-5):i+5]):
                patterns.append({
                    "name": "react_component_pattern",
                    "domain": "frontend",
                    "description": f"React component in {filepath}",
                    "code_example": stripped[:200],
                    "confidence": 0.5,
                })

        # API route pattern
        if re.match(r"(app|router)\.(get|post|put|delete)\(", stripped):
            patterns.append({
                "name": f"api_route_{stripped.split('(')[0].split('.')[-1]}",
                "domain": domain,
                "description": f"API route: {stripped[:100]}",
                "code_example": stripped[:200],
                "confidence": 0.6,
            })

    return patterns


def _extract_rust_patterns(lines: list[str], filepath: str) -> list[dict]:
    patterns = []
    domain = "rust"

    for i, line in enumerate(lines):
        stripped = line.strip()

        # Trait implementation
        if stripped.startswith("impl") and "for" in stripped:
            patterns.append({
                "name": "trait_impl_pattern",
                "domain": domain,
                "description": f"Trait implementation: {stripped[:100]}",
                "code_example": "",
                "confidence": 0.5,
            })

        # Error handling with Result
        if "-> Result" in stripped or "unwrap()" in stripped:
            patterns.append({
                "name": "rust_error_handling",
                "domain": domain,
                "description": f"Result-based error handling in {filepath}",
                "code_example": "",
                "confidence": 0.4,
            })

    return patterns


def _extract_go_patterns(lines: list[str], filepath: str) -> list[dict]:
    patterns = []
    domain = "go"

    for i, line in enumerate(lines):
        stripped = line.strip()

        # HTTP handler pattern
        if "http.HandleFunc" in stripped or "http.Handler" in stripped:
            patterns.append({
                "name": "go_http_handler",
                "domain": domain,
                "description": f"HTTP handler: {stripped[:100]}",
                "code_example": stripped[:200],
                "confidence": 0.5,
            })

        # Goroutine pattern
        if "go func" in stripped:
            patterns.append({
                "name": "go_goroutine_pattern",
                "domain": domain,
                "description": f"Goroutine usage in {filepath}",
                "code_example": "",
                "confidence": 0.4,
            })

    return patterns


def _infer_domain(filepath: str) -> str:
    fp = filepath.lower()
    if any(k in fp for k in ("test", "spec", "_test")):
        return "testing"
    if any(k in fp for k in ("api", "route", "handler", "view", "controller")):
        return "api"
    if any(k in fp for k in ("model", "schema", "db", "migration")):
        return "data"
    if any(k in fp for k in ("config", "deploy", "ci", "docker")):
        return "devops"
    return "general"
