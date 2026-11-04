"""N5 RuleClaimExtractor: regex extraction of path/command/flag/symbol claims."""

from __future__ import annotations

import re

from ...contracts.claims import Claim, ClaimSet, DocText
from ...contracts.envelope import Envelope
from ...observability.decorators import logged_step

AGENT_ID = "N5.RuleClaimExtractor"

BACKTICK = re.compile(r"`([^`\n]+)`")
MAKE_CMD = re.compile(r"\bmake\s+([\w][\w.-]*)")
NPM_CMD = re.compile(r"\bnpm\s+run\s+([\w:.-]+)")
FLAG = re.compile(r"--[\w][\w-]*")
PATH_LIKE = re.compile(r"(?:^|[\s\"'(])((?:[\w.-]+/)+[\w.-]+(?:\.[\w]+)?)")

# Bare tool / format words that are never repo symbols.
TOOL_NAMES = frozenset(
    {
        "npm", "make", "git", "python", "python3", "pip", "pip3",
        "node", "npx", "yarn", "pnpm", "docker", "uv", "poetry",
        "conda", "mamba", "bash", "sh", "zsh", "fish", "powershell",
        "cmd", "curl", "wget", "pytest", "mypy", "ruff", "black",
        "flake8", "tox", "nox", "cargo", "go", "java", "ruby",
        "kubectl", "terraform", "gradle", "cmake", "ninja",
        "html", "markdown", "md", "mdx", "rst", "sphinx",
        "json", "yaml", "yml", "toml", "xml", "csv", "env",
    }
)

_IDENT_PART = re.compile(r"[A-Za-z_][A-Za-z0-9_]*")
_IMPORT_LINE = re.compile(r"^\s*(import|from)\b")
_NOISE_PATH = re.compile(
    r"(^|/)(conftest\.py|teardown[^/]*|\.test\.[^/]+|[^/]*\.spec\.[^/]+)$"
)


def _normalize(text: str) -> str:
    return re.sub(r"[^a-z0-9]+", "", text.lower())


def _skip_token(token: str) -> bool:
    """Noise tokens that must not become claims: prose, placeholders, dotfiles."""
    if not token or not token.strip():
        return True
    if any(ch.isspace() for ch in token):
        return True
    if "..." in token or "*" in token:
        return True
    if token[0] in "<[{" or token[-1] in ">}]":
        return True
    if token.startswith(".") and "/" not in token and "\\" not in token:
        return True
    return token.lower() in TOOL_NAMES


def _looks_like_symbol(token: str) -> bool:
    """Dotted names whose every part is an identifier (e.g. `a.b.C`)."""
    return bool(token) and all(
        _IDENT_PART.fullmatch(part) for part in token.split(".")
    )


def extract(doc: DocText) -> ClaimSet:
    claims: list[Claim] = []
    seen: set[str] = set()
    for idx, line in enumerate(doc.lines, start=1):
        import_line = bool(_IMPORT_LINE.match(line))
        for token in BACKTICK.findall(line):
            if _skip_token(token):
                continue
            if import_line:
                continue
            if _NOISE_PATH.search(token):
                continue
            kind = "symbol"
            if "/" in token or token.endswith(".md"):
                kind = "path"
            elif token.startswith("make ") or token.startswith("npm "):
                kind = "command"
            elif token.startswith("--"):
                kind = "command"
            elif not _looks_like_symbol(token):
                continue
            key = kind + ":" + _normalize(token)
            if key in seen:
                continue
            seen.add(key)
            claims.append(
                Claim(
                    id=Claim.make_id(doc.doc_path, idx, token),
                    doc_path=doc.doc_path,
                    line=idx,
                    text=token,
                    kind=kind,
                    feature=doc.feature,
                    refs=[token],
                )
            )
        for make_target in MAKE_CMD.findall(line):
            cmd = f"make {make_target}"
            key = "command:" + _normalize(cmd)
            if key in seen:
                continue
            seen.add(key)
            claims.append(
                Claim(
                    id=Claim.make_id(doc.doc_path, idx, cmd),
                    doc_path=doc.doc_path,
                    line=idx,
                    text=cmd,
                    kind="command",
                    feature=doc.feature,
                    refs=[cmd],
                )
            )
        for script in NPM_CMD.findall(line):
            cmd = f"npm run {script}"
            key = "command:" + _normalize(cmd)
            if key in seen:
                continue
            seen.add(key)
            claims.append(
                Claim(
                    id=Claim.make_id(doc.doc_path, idx, cmd),
                    doc_path=doc.doc_path,
                    line=idx,
                    text=cmd,
                    kind="command",
                    feature=doc.feature,
                    refs=[cmd],
                )
            )
    return ClaimSet(doc_path=doc.doc_path, claims=claims)


@logged_step(AGENT_ID)
def handle(env: Envelope[DocText]) -> Envelope[ClaimSet]:
    doc = env.payload if isinstance(env.payload, DocText) else DocText()
    result = extract(doc)
    return Envelope[ClaimSet](
        correlation_id=env.correlation_id,
        type="ClaimSet",
        sender=AGENT_ID,
        recipient=env.sender or "Orchestrator",
        payload=result,
    )
