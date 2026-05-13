"""Generate an educational, book-style code reference of the production codebase.

This script walks the production tree, parses each .py file with the ast
module, and extracts a deep description of every module: classes, functions,
signatures, full docstrings, and the Python language features the module
demonstrates (async, generators, decorators, dataclasses, comprehensions,
context managers, properties, type hints, etc.).

It then renders a multi-chapter PDF designed to read like a book — opening
with a Python concepts primer, walking through each module with prose that
explains both *what the code does* and *which Python concepts are at play*,
and closing with a glossary plus an index that maps each Python concept back
to the modules where it is used in real code.
"""

from __future__ import annotations

import ast
import re
import textwrap
from pathlib import Path
from collections import Counter, defaultdict

from reportlab.lib import colors
from reportlab.lib.pagesizes import LETTER
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import inch
from reportlab.platypus import (
    BaseDocTemplate,
    Frame,
    KeepTogether,
    PageBreak,
    PageTemplate,
    Paragraph,
    Preformatted,
    Spacer,
    Table,
    TableStyle,
)


REPO_ROOT = Path(__file__).resolve().parent


def esc(s: str) -> str:
    """Escape text for reportlab Paragraph (which uses minimal HTML)."""
    return s.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


# ---------------------------------------------------------------------------
# 1a.  Per-constant explainer
# ---------------------------------------------------------------------------
#
# Module-level constants (UPPER_CASE = ...) used to be dumped as a flat code
# block.  This helper produces a one-sentence plain-English explanation of
# each line — the same line-by-line style we use when walking through code
# in the chapter prose.  Falls back to a generic note if no pattern matches.

_CONST_GETENV_BARE = re.compile(
    r"^os\.getenv\(\s*['\"]([^'\"]+)['\"]\s*(?:,\s*(.+?))?\s*\)\s*$"
)
_CONST_GETENV_INT = re.compile(
    r"^int\(\s*os\.getenv\(\s*['\"]([^'\"]+)['\"]\s*(?:,\s*(.+?))?\s*\)\s*\)\s*$"
)
_CONST_GETENV_FLOAT = re.compile(
    r"^float\(\s*os\.getenv\(\s*['\"]([^'\"]+)['\"]\s*(?:,\s*(.+?))?\s*\)\s*\)\s*$"
)
_CONST_GETENV_BOOL = re.compile(
    r"^os\.getenv\(\s*['\"]([^'\"]+)['\"]\s*(?:,\s*(.+?))?\s*\)\s*"
    r"\.lower\(\)\s*==\s*['\"]true['\"]\s*$"
)
_CONST_OS_ENVIRON = re.compile(
    r"^os\.environ\.get\(\s*['\"]([^'\"]+)['\"]\s*(?:,\s*(.+?))?\s*\)\s*$"
)
_CONST_URL = re.compile(r"^['\"](https?://[^'\"]+)['\"]\s*$")
_CONST_PLAIN_STR = re.compile(r"^['\"][^'\"]*['\"]\s*$")
_CONST_NUMBER = re.compile(r"^-?\d+(\.\d+)?\s*$")


def explain_constant(line: str) -> str:
    """Return a one-sentence explanation of a `NAME = value` constant line.

    Recognises common configuration patterns (env-var lookups with defaults,
    type-cast env vars, boolean feature flags, URLs, loggers, paths) and
    falls back to a generic note otherwise.  Returns reportlab-flavoured
    HTML (so callers can drop the result straight into a Paragraph).
    """
    if "=" not in line:
        return ""
    name, _, raw = line.partition("=")
    name = name.strip()
    value = raw.strip()
    if ":" in name and not name.endswith(":"):
        name = name.split(":", 1)[0].strip()

    m = _CONST_GETENV_INT.match(value)
    if m:
        env, default = m.group(1), m.group(2)
        if default:
            return (
                f"Reads <code>{esc(env)}</code> from the environment and "
                f"converts it to <code>int</code> (env vars are always "
                f"strings). Falls back to <code>{esc(default)}</code> "
                f"when unset."
            )
        return (
            f"Reads <code>{esc(env)}</code> from the environment and "
            f"converts it to <code>int</code>; required (no default)."
        )

    m = _CONST_GETENV_FLOAT.match(value)
    if m:
        env, default = m.group(1), m.group(2)
        if default:
            return (
                f"Reads <code>{esc(env)}</code> from the environment and "
                f"casts it to <code>float</code>. Defaults to "
                f"<code>{esc(default)}</code> when unset."
            )
        return (
            f"Reads <code>{esc(env)}</code> from the environment and "
            f"casts it to <code>float</code>."
        )

    m = _CONST_GETENV_BOOL.match(value)
    if m:
        env, default = m.group(1), m.group(2)
        tail = (
            f"Defaults to <code>{esc(default)}</code>."
            if default else "Treated as <code>False</code> if unset."
        )
        return (
            f"Boolean feature flag. Reads <code>{esc(env)}</code> from "
            f"the environment, lowercases it, and compares to "
            f"<code>'true'</code> &mdash; producing a real Python "
            f"<code>bool</code>. {tail}"
        )

    m = _CONST_GETENV_BARE.match(value)
    if m:
        env, default = m.group(1), m.group(2)
        if default:
            return (
                f"Reads <code>{esc(env)}</code> from the environment, "
                f"defaulting to <code>{esc(default)}</code> when not set "
                f"&mdash; overridable per environment without a code change."
            )
        return (
            f"Reads <code>{esc(env)}</code> from the environment. "
            f"Returns <code>None</code> if unset."
        )

    m = _CONST_OS_ENVIRON.match(value)
    if m:
        env, default = m.group(1), m.group(2)
        if default:
            return (
                f"Equivalent to <code>os.getenv</code>: reads "
                f"<code>{esc(env)}</code> from the environment, default "
                f"<code>{esc(default)}</code>."
            )
        return (
            f"Reads <code>{esc(env)}</code> from <code>os.environ</code> "
            f"(returns <code>None</code> if unset)."
        )

    if "logging.getLogger" in value:
        return (
            "Module-level logger &mdash; every log line in this file flows "
            "through it, named after the module so logs can be filtered "
            "by source."
        )

    if _CONST_URL.match(value):
        return (
            "URL constant pointing to an external resource. Hard-coded at "
            "load time; change here, not in callers."
        )

    if "Path(__file__)" in value or "__file__" in value:
        return (
            "Filesystem path resolved relative to the source file at "
            "import time &mdash; portable across machines."
        )

    if value.startswith("Path(") or "pathlib.Path" in value:
        return "Filesystem path constant built with <code>pathlib.Path</code>."

    if _CONST_PLAIN_STR.match(value):
        return "String literal &mdash; fixed at code-load time."

    if _CONST_NUMBER.match(value):
        return (
            "Numeric literal &mdash; a tunable parameter compiled into "
            "the source."
        )

    if value.startswith("[") or value.startswith("("):
        return (
            "Collection literal &mdash; a fixed set of values referenced "
            "elsewhere in the module."
        )
    if value.startswith("{"):
        return (
            "Mapping or set literal &mdash; a lookup table referenced "
            "elsewhere in the module."
        )

    if value.startswith("re.compile"):
        return (
            "Pre-compiled regular expression &mdash; compiled once at "
            "import time and reused, which is faster than compiling on "
            "every call."
        )

    return (
        "Module-level constant &mdash; bound once at import time and "
        "referenced from the functions and classes below."
    )


# ---------------------------------------------------------------------------
# 1.  File selection
# ---------------------------------------------------------------------------

DASHBOARD_PROD_FILES = {
    "api_client.py",
    "app.py",
    "calc_like_sheet.py",
    "database.py",
    "db.py",
    "email_service.py",
    "financial_overview.py",
    "manage_api_keys.py",
    "models.py",
    "notes_service.py",
    "phase_manager.py",
    "scheduler.py",
    "watermark_service.py",
}

ROOT_PROD_FILES = {
    "build.py",
    "gunicorn.conf.py",
    "manage_users.py",
    "migrations.py",
    "prepare_deployment.py",
    "wsgi.py",
}


def collect_files() -> list[Path]:
    files: list[Path] = []

    for name in sorted(ROOT_PROD_FILES):
        p = REPO_ROOT / name
        if p.exists():
            files.append(p)

    tc = REPO_ROOT / "trader_companion"
    for path in sorted(tc.rglob("*.py")):
        if "__pycache__" in path.parts or "build" in path.parts or "dist" in path.parts:
            continue
        if path.name == "trader_app_backup.py":
            continue
        files.append(path)

    for name in sorted(DASHBOARD_PROD_FILES):
        p = REPO_ROOT / "dashboard" / name
        if p.exists():
            files.append(p)
    for path in sorted((REPO_ROOT / "dashboard" / "utils").glob("*.py")):
        files.append(path)

    for d in ("connectors", "config", "utils"):
        for path in sorted((REPO_ROOT / d).rglob("*.py")):
            if "__pycache__" in path.parts:
                continue
            files.append(path)

    for path in sorted((REPO_ROOT / "alembic").rglob("*.py")):
        if "__pycache__" in path.parts:
            continue
        files.append(path)

    seen, unique = set(), []
    for f in files:
        if f not in seen:
            seen.add(f)
            unique.append(f)
    return unique


# ---------------------------------------------------------------------------
# 2.  AST extraction with feature detection
# ---------------------------------------------------------------------------


def fmt_arg(a: ast.arg, default: ast.AST | None = None) -> str:
    s = a.arg
    if a.annotation is not None:
        try:
            s += ": " + ast.unparse(a.annotation)
        except Exception:
            pass
    if default is not None:
        try:
            s += "=" + ast.unparse(default)
        except Exception:
            s += "=..."
    return s


def fmt_signature(node: ast.FunctionDef | ast.AsyncFunctionDef) -> str:
    args = node.args
    parts: list[str] = []

    pos_only = list(args.posonlyargs)
    pos = list(args.args)
    defaults = list(args.defaults)
    n_defaults = len(defaults)
    n_total_pos = len(pos_only) + len(pos)
    pos_default_pad = [None] * (n_total_pos - n_defaults) + defaults
    all_pos = pos_only + pos
    for i, a in enumerate(all_pos):
        parts.append(fmt_arg(a, pos_default_pad[i]))
        if pos_only and i == len(pos_only) - 1:
            parts.append("/")

    if args.vararg:
        parts.append("*" + fmt_arg(args.vararg))
    elif args.kwonlyargs:
        parts.append("*")

    for a, d in zip(args.kwonlyargs, args.kw_defaults):
        parts.append(fmt_arg(a, d))

    if args.kwarg:
        parts.append("**" + fmt_arg(args.kwarg))

    sig = "(" + ", ".join(parts) + ")"
    if node.returns is not None:
        try:
            sig += " -> " + ast.unparse(node.returns)
        except Exception:
            pass

    prefix = "async def " if isinstance(node, ast.AsyncFunctionDef) else "def "
    decos = [f"@{ast.unparse(d)}" for d in node.decorator_list]
    return ("\n".join(decos) + ("\n" if decos else "")) + prefix + node.name + sig


# ---------------------------------------------------------------------------
# 1a.  Module knowledge base — used to enrich the per-import section
# ---------------------------------------------------------------------------


MODULE_KB: dict[str, dict] = {
    # ---- standard library --------------------------------------------------
    "os": {
        "why": "Operating-system interface. Path manipulation, environment "
               "variables, working-directory operations, exit codes, and "
               "thin wrappers around POSIX/Windows syscalls.",
        "example": "os.path.join(root, 'subdir', 'file.txt')  "
                   "# joins with the OS-correct separator",
        "others": [
            "os.environ.get('API_KEY') to read environment variables",
            "os.makedirs(path, exist_ok=True) to create nested directories",
            "os.listdir(path) to list a directory's contents",
            "os.remove(path) / os.rename(src, dst) to delete or move a file",
            "os.getcwd() / os.chdir(path) to inspect or change the working dir",
        ],
    },
    "sys": {
        "why": "Access to the running interpreter — argv, stdin/stdout, exit "
               "codes, the import search path, and the platform name.",
        "example": "sys.exit(1)  # terminate the process with a non-zero status",
        "others": [
            "sys.argv[1:] reads the command-line arguments",
            "sys.path.insert(0, '/extra') prepends to the import search path",
            "sys.stderr.write(msg) writes to standard error",
            "sys.platform tells you 'win32', 'linux', or 'darwin'",
            "sys.modules is the global cache of already-imported modules",
        ],
    },
    "shutil": {
        "why": "High-level filesystem operations: copying trees, moving "
               "files across filesystems, deleting directories, locating "
               "executables on PATH.",
        "example": "shutil.copytree(src, dst)  # recursively copies a tree",
        "others": [
            "shutil.move(src, dst) moves or renames",
            "shutil.rmtree(path) deletes a directory and all its contents",
            "shutil.which('git') finds an executable on PATH",
            "shutil.disk_usage(path) returns total / used / free bytes",
        ],
    },
    "subprocess": {
        "why": "Run external programs. The standard way to spawn a child "
               "process, capture its output, and wait for its exit code.",
        "example": "subprocess.run(['git', 'rev-parse', 'HEAD'], "
                   "capture_output=True, text=True, check=True)",
        "others": [
            "Popen(...) for streaming I/O while the process is alive",
            "check_output(cmd) returns stdout as text and raises on failure",
            "DEVNULL / PIPE redirect stdin/stdout/stderr",
            "shell=True interprets the string with the system shell (security risk)",
        ],
    },
    "pathlib": {
        "why": "Object-oriented filesystem paths. Replaces most uses of "
               "os.path with chainable methods and operator overloading.",
        "example": "Path('logs') / f'{name}.log'  # / is overloaded to join",
        "others": [
            "p.exists(), p.is_file(), p.is_dir() for predicates",
            "p.read_text() / p.write_text(content) for one-shot file I/O",
            "p.glob('**/*.py') to walk a tree with a pattern",
            "p.with_suffix('.bak') to derive a sibling path",
        ],
    },
    "re": {
        "why": "Regular expressions. Pattern matching, search, replace, "
               "and text extraction.",
        "example": "re.search(r'\\d{3}-\\d{4}', text)  "
                   "# returns a Match or None",
        "others": [
            "re.findall(pattern, text) for every non-overlapping match",
            "re.sub(pattern, repl, text) to replace occurrences",
            "re.compile(...) to reuse a pattern (faster in a loop)",
            "Named groups: r'(?P<year>\\d{4})' lets you do m.group('year')",
        ],
    },
    "json": {
        "why": "JSON encoding and decoding — the standard wire format for "
               "config files, API payloads, and inter-process messages.",
        "example": "json.loads(response.text)  # parse a JSON string to dict",
        "others": [
            "json.dumps(obj, indent=2) for pretty-printing",
            "json.dump(obj, file) / json.load(file) for file I/O",
            "default=str handles non-serialisable types like datetime",
            "object_hook= customises decoding (e.g., to dataclass instances)",
        ],
    },
    "datetime": {
        "why": "Dates, times, durations. The fundamental temporal types: "
               "date, time, datetime, timedelta, timezone.",
        "example": "datetime.now() - timedelta(days=7)  # one week ago",
        "others": [
            "datetime.strptime(s, '%Y-%m-%d') parses a string",
            "datetime.strftime(fmt) formats one",
            "datetime.fromtimestamp(n) converts a Unix epoch",
            "datetime.utcnow() for UTC (better: datetime.now(timezone.utc))",
        ],
    },
    "time": {
        "why": "Timestamps and sleep. Lower-level than datetime — works in "
               "Unix-epoch seconds.",
        "example": "time.sleep(1.5)  # pause this thread for 1.5 seconds",
        "others": [
            "time.time() returns seconds since the epoch",
            "time.monotonic() for measuring elapsed time (never goes backward)",
            "time.perf_counter() for high-precision benchmarking",
            "time.strftime / time.strptime mirror the datetime versions",
        ],
    },
    "logging": {
        "why": "Structured, levelled logging. Replaces print() with "
               "filterable, formattable output that can route to files, "
               "stderr, syslog, or HTTP endpoints.",
        "example": "logging.getLogger(__name__).info('connected to %s', host)",
        "others": [
            ".debug() / .info() / .warning() / .error() / .exception()",
            "logger.exception() captures the current traceback automatically",
            "logging.basicConfig(level=logging.INFO) for quick setup",
            "Handlers and Formatters route logs to files / streams / syslog",
        ],
    },
    "threading": {
        "why": "Threads and synchronisation primitives. Used when work is "
               "I/O-bound and the GIL is not a bottleneck (the GIL prevents "
               "speed-up on CPU-bound work).",
        "example": "Thread(target=worker, args=(q,), daemon=True).start()",
        "others": [
            "Lock / RLock to guard shared state",
            "Event for one-shot signals between threads",
            "Queue (from queue) for producer/consumer patterns",
            "threading.local() for thread-local storage",
        ],
    },
    "asyncio": {
        "why": "The event loop and primitives behind async/await. Schedules "
               "coroutines, runs network I/O without blocking, and "
               "coordinates concurrent tasks.",
        "example": "asyncio.run(main())  # entry point that drives the loop",
        "others": [
            "asyncio.create_task(coro) schedules a coroutine concurrently",
            "asyncio.gather(*tasks) awaits many at once and collects results",
            "asyncio.sleep(s) yields control instead of blocking",
            "asyncio.Queue is the async-aware producer/consumer queue",
        ],
    },
    "collections": {
        "why": "Specialised container datatypes that the dict / list / "
               "tuple / set primitives don't cover.",
        "example": "Counter(words)  # multiset that counts occurrences",
        "others": [
            "defaultdict(list) auto-creates a default value on missing keys",
            "deque(maxlen=N) is a double-ended bounded queue",
            "OrderedDict (mostly redundant since 3.7 — dicts preserve order)",
            "namedtuple('Point', 'x y') for tiny immutable record types",
        ],
    },
    "functools": {
        "why": "Higher-order helpers — caching, partial application, "
               "decorator authoring tools, reducers.",
        "example": "@lru_cache(maxsize=128)  # memoise this pure function",
        "others": [
            "partial(f, x=1) pre-binds arguments",
            "reduce(f, iterable) folds an iterable to a single value",
            "@wraps(fn) preserves __name__/__doc__ when writing decorators",
            "@cached_property memoises a property per-instance",
        ],
    },
    "itertools": {
        "why": "Iterator algebra — chain, zip-pad, windowed views, "
               "permutations, lazy infinite streams.",
        "example": "itertools.chain.from_iterable(list_of_lists)",
        "others": [
            "groupby(iter, key=fn) groups consecutive equal-key items",
            "islice(iter, start, stop) for lazy slicing",
            "product(a, b) is the Cartesian product",
            "combinations(iter, r) and permutations(iter, r) for subsets",
        ],
    },
    "typing": {
        "why": "Type-hint primitives — generics, unions, Optional, Callable, "
               "Protocol, TypeVar, TypedDict.",
        "example": "def lookup(k: str) -> Optional[int]: ...",
        "others": [
            "List[int] / Dict[str, Any] / Tuple[int, str] (or bare list[int]+ on 3.9+)",
            "Callable[[int, int], int] for function signatures",
            "Protocol for structural typing (duck typing with checks)",
            "TypeVar('T') for generic functions and classes",
        ],
    },
    "dataclasses": {
        "why": "@dataclass auto-generates __init__/__repr__/__eq__ from "
               "annotated fields — boilerplate-free record types.",
        "example": "@dataclass\\nclass Trade:\\n    symbol: str\\n    "
                   "volume: float = 0.1",
        "others": [
            "field(default_factory=list) for mutable defaults (NEVER use = [])",
            "frozen=True makes instances hashable and immutable",
            "asdict(obj) / astuple(obj) convert to dict or tuple",
            "@dataclass(slots=True) saves memory (3.10+)",
        ],
    },
    "enum": {
        "why": "Enumerated constants. Replaces magic strings/numbers with a "
               "type that has both a name and a value.",
        "example": "class Phase(Enum):\\n    CHALLENGE = 'challenge'\\n    "
                   "FUNDED = 'funded'",
        "others": [
            "IntEnum for an enum that compares equal to its int value",
            "auto() lets you skip explicit values",
            "Phase['CHALLENGE'] looks up by name; Phase('challenge') by value",
        ],
    },
    "abc": {
        "why": "Abstract base classes. Define an interface that subclasses "
               "must implement; instantiating an incomplete subclass raises.",
        "example": "class Storage(ABC):\\n    @abstractmethod\\n    "
                   "def put(self, k, v): ...",
        "others": [
            "@abstractmethod inside an ABC marks a required override",
            "abc.ABCMeta is the metaclass ABC inherits from",
            "register() lets a class be considered a virtual subclass",
        ],
    },
    "contextlib": {
        "why": "Context-manager helpers. @contextmanager turns a generator "
               "into a with-block; suppress() swallows specific exceptions.",
        "example": "@contextmanager\\ndef timer():\\n    t=time.time(); "
                   "yield; print(time.time()-t)",
        "others": [
            "ExitStack stacks dynamic context managers (close many at once)",
            "suppress(FileNotFoundError) ignores a specific exception",
            "closing(obj) wraps any close()-able as a context manager",
        ],
    },
    "hashlib": {
        "why": "Cryptographic hash functions — SHA-256, MD5, BLAKE2.",
        "example": "hashlib.sha256(b'hello').hexdigest()",
        "others": [
            "Pass data in chunks via .update() to hash large files",
            "Use sha256 / sha512 for integrity; never MD5 or SHA-1 for security",
            "For password hashing use bcrypt/argon2, NOT raw hashlib",
        ],
    },
    "secrets": {
        "why": "Cryptographically strong randomness — tokens, session IDs, "
               "API keys. Never use random for anything security-sensitive.",
        "example": "secrets.token_urlsafe(32)  # 32-byte url-safe random string",
        "others": [
            "secrets.token_hex(n) for a hex string",
            "secrets.choice(seq) is the cryptographic equivalent of random.choice",
            "secrets.compare_digest(a, b) for timing-safe comparison",
        ],
    },
    "random": {
        "why": "Pseudo-random numbers — fine for jitter, sampling, shuffling. "
               "NEVER for security; use secrets for that.",
        "example": "random.uniform(0.5, 1.5)  # backoff jitter",
        "others": [
            "random.choice(seq) picks one item",
            "random.shuffle(list) rearranges in place",
            "random.seed(n) makes the sequence reproducible",
            "random.sample(seq, k) draws k unique items",
        ],
    },
    "math": {
        "why": "Math functions — log, sqrt, trig, constants. Pure scalar "
               "operations (vectorised math lives in numpy).",
        "example": "math.sqrt(x*x + y*y)",
        "others": [
            "math.inf / math.nan / math.pi / math.e",
            "math.isnan(x), math.isinf(x) for predicates",
            "math.floor(x), math.ceil(x), math.trunc(x) for rounding",
        ],
    },
    "io": {
        "why": "In-memory streams and the abstract base classes for file "
               "objects. Useful when an API expects a file but you only "
               "have bytes/text in memory.",
        "example": "io.BytesIO(b'data')  # behaves like an open binary file",
        "others": [
            "io.StringIO('text') for an in-memory text stream",
            "io.TextIOWrapper wraps a binary stream with an encoding",
        ],
    },
    "csv": {
        "why": "CSV reading and writing. Handles quoting, escaping, and "
               "different dialects.",
        "example": "for row in csv.DictReader(open(path)): ...",
        "others": [
            "csv.writer(f).writerow([...])",
            "csv.DictWriter(f, fieldnames=[...]) for header-aware output",
            "Pass newline='' to open() — csv handles its own line endings",
        ],
    },
    "sqlite3": {
        "why": "Built-in SQLite driver. Zero-configuration embedded database "
               "for caches, dev databases, and small persistent state.",
        "example": "sqlite3.connect('cache.db')  # creates if missing",
        "others": [
            "conn.execute('SELECT ?', (val,)) — always parameterise",
            "conn.row_factory = sqlite3.Row for dict-like rows",
            "Use a single connection per thread (or check_same_thread=False)",
        ],
    },
    "pickle": {
        "why": "Serialise Python objects to bytes. Convenient but UNSAFE "
               "to load untrusted input — pickle can execute arbitrary code.",
        "example": "pickle.dumps(obj) / pickle.loads(blob)",
        "others": [
            "Prefer JSON or a schema-aware format for data interchange",
            "Use only between trusted Python processes you control",
        ],
    },
    "traceback": {
        "why": "Format and inspect exception tracebacks. Used to log a full "
               "stack trace without re-raising.",
        "example": "logger.error(traceback.format_exc())",
        "others": [
            "traceback.print_exc() prints to stderr",
            "traceback.format_exception(type, value, tb) for custom handling",
        ],
    },
    "tempfile": {
        "why": "Temporary files and directories that clean themselves up.",
        "example": "with tempfile.TemporaryDirectory() as d: ...",
        "others": [
            "tempfile.NamedTemporaryFile(delete=False) for a real path on disk",
            "tempfile.mkstemp() returns a low-level (fd, path) pair",
        ],
    },
    "argparse": {
        "why": "Command-line argument parsing. Generates --help, type-coerces "
               "values, and dispatches sub-commands.",
        "example": "parser.add_argument('--verbose', action='store_true')",
        "others": [
            "type=int / type=Path coerces the value",
            "subparsers for git-style sub-commands",
            "ArgumentDefaultsHelpFormatter shows defaults in --help",
        ],
    },
    "socket": {
        "why": "BSD-style sockets — TCP/UDP/Unix-domain primitives.",
        "example": "socket.gethostbyname('example.com')",
        "others": [
            "socket.create_connection((host, port), timeout=5)",
            "Use a higher-level library (requests, websockets) when you can",
        ],
    },
    "urllib": {
        "why": "Stdlib URL utilities — parsing, encoding, and a basic HTTP "
               "client. Mostly useful for the parsing helpers; for outbound "
               "HTTP, requests is more pleasant.",
        "example": "urllib.parse.urlencode({'q': 'hello world'})",
        "others": [
            "urllib.parse.urlparse(url) splits scheme/host/path/query",
            "urllib.parse.quote(s) percent-encodes a path segment",
            "urllib.request.urlopen(url) is the basic HTTP client",
        ],
    },
    "smtplib": {
        "why": "SMTP client — sending email. Pairs with the email package, "
               "which builds the MIME message.",
        "example": "smtp.send_message(msg)  # where msg is an EmailMessage",
        "others": [
            "SMTP_SSL(host, 465) for implicit-TLS providers",
            "starttls() upgrades a plain connection to TLS",
            "login(user, password) authenticates",
        ],
    },
    "email": {
        "why": "Build and parse email messages — headers, MIME parts, "
               "attachments. Pairs with smtplib for sending.",
        "example": "msg = EmailMessage(); msg['To'] = 'a@b.com'; "
                   "msg.set_content('hi')",
        "others": [
            "msg.add_attachment(data, maintype='application', subtype='pdf')",
            "email.utils.formataddr(('Name', 'a@b.com')) builds an addr",
        ],
    },
    "tkinter": {
        "why": "The standard-library GUI toolkit. Powers the desktop trader "
               "companion's window.",
        "example": "root = tk.Tk(); tk.Button(root, text='Go').pack()",
        "others": [
            "ttk.* for the modern themed widgets (Treeview, Notebook, ...)",
            "after(ms, fn) schedules a callback on the GUI thread",
            "StringVar / IntVar bind variables to widgets",
        ],
    },
    "concurrent": {
        "why": "concurrent.futures — high-level pools of threads or "
               "processes. Submit work, get back a Future you can await.",
        "example": "with ThreadPoolExecutor(8) as ex: results = "
                   "list(ex.map(fetch, urls))",
        "others": [
            "ProcessPoolExecutor for CPU-bound work (sidesteps the GIL)",
            "ex.submit(fn, *args) returns a Future",
            "as_completed(futures) yields them in completion order",
        ],
    },
    "queue": {
        "why": "Thread-safe FIFO/LIFO/priority queues — the canonical "
               "producer/consumer primitive.",
        "example": "q = Queue(); q.put(item); item = q.get()",
        "others": [
            "LifoQueue for stack semantics",
            "PriorityQueue uses (priority, item) tuples",
            "q.task_done() / q.join() coordinate worker shutdown",
        ],
    },
    "signal": {
        "why": "Receive POSIX/Windows signals — SIGINT (Ctrl-C), SIGTERM, "
               "etc. Used to install graceful-shutdown handlers.",
        "example": "signal.signal(signal.SIGTERM, on_term)",
        "others": [
            "Only the main thread can install handlers",
            "On Windows, SIGTERM is mostly equivalent to a force-kill",
        ],
    },
    "warnings": {
        "why": "Issue and filter deprecation/runtime warnings — softer than "
               "an exception, louder than a log line.",
        "example": "warnings.warn('use new_api()', DeprecationWarning)",
        "others": [
            "warnings.filterwarnings('ignore', category=...) silences a class",
            "Treat warnings as errors in tests with -W error",
        ],
    },
    "copy": {
        "why": "Shallow and deep copies of arbitrary objects.",
        "example": "deepcopy(state)  # safe to mutate without aliasing",
        "others": [
            "copy.copy(x) is shallow — nested mutables stay shared",
            "Custom __copy__ / __deepcopy__ hooks let classes opt out",
        ],
    },
    "ctypes": {
        "why": "Call C functions from shared libraries (DLLs / .so / .dylib). "
               "Used here to reach Win32 APIs the stdlib doesn't expose.",
        "example": "ctypes.windll.user32.MessageBoxW(0, 'hi', 't', 0)",
        "others": [
            "CDLL('libfoo.so') loads a Unix shared object",
            "Define argtypes/restype to get type-checked calls",
            "c_int / c_char_p / Structure mirror C type layouts",
        ],
    },
    "winreg": {
        "why": "Read and write the Windows registry — used to discover "
               "installed MetaTrader terminals.",
        "example": "winreg.OpenKey(HKEY_LOCAL_MACHINE, r'Software\\\\X')",
        "others": [
            "QueryValueEx returns a (value, type) tuple",
            "EnumKey / EnumValue iterate sub-keys",
        ],
    },
    "psutil": {
        "why": "Cross-platform process and system information — find a "
               "running terminal, check CPU/memory, kill a stale process.",
        "example": "psutil.process_iter(['name'])  # iterate live processes",
        "others": [
            "psutil.Process(pid).terminate() / .kill()",
            "psutil.cpu_percent(interval=1.0) measures CPU usage",
            "psutil.virtual_memory() returns RAM stats",
        ],
    },
    "gzip": {
        "why": "Read/write gzip-compressed streams.",
        "example": "with gzip.open('logs.gz', 'rt') as f: ...",
        "others": [
            "gzip.compress(b) / gzip.decompress(b) for in-memory blobs",
            "Pair with shutil.copyfileobj for streaming compression",
        ],
    },
    "websocket": {
        "why": "websocket-client — synchronous WebSocket client. Used here "
               "to subscribe to broker price feeds and order updates.",
        "example": "ws = websocket.WebSocketApp(url, on_message=on_msg)",
        "others": [
            "WebSocketApp.run_forever() blocks and handles reconnects",
            "Send via ws.send(json.dumps(msg))",
        ],
    },
    "win32com": {
        "why": "pywin32's COM bridge. Drives Windows applications that "
               "expose an Automation interface.",
        "example": "win32com.client.Dispatch('Outlook.Application')",
        "others": [
            "client.GetActiveObject(progid) attaches to an existing instance",
            "Method/property access mirrors the COM object",
        ],
    },
    "pytz": {
        "why": "Olson timezone database for Python. Mostly superseded by "
               "the stdlib zoneinfo (3.9+) but still common.",
        "example": "pytz.timezone('America/New_York').localize(naive_dt)",
        "others": [
            "tz.normalize(dt) handles DST transitions",
            "On 3.9+ prefer zoneinfo.ZoneInfo('America/New_York')",
        ],
    },

    # ---- third-party -------------------------------------------------------
    "requests": {
        "why": "The de-facto Python HTTP client. Synchronous; trades raw "
               "speed for an extremely friendly API.",
        "example": "requests.get(url, timeout=10).json()",
        "others": [
            "Session() reuses TCP connections across calls",
            "params=, headers=, json=, data= for query/body shapes",
            "raise_for_status() turns 4xx/5xx into an exception",
            "stream=True for large downloads",
        ],
    },
    "flask": {
        "why": "Lightweight WSGI web framework. Powers the dashboard.",
        "example": "@app.route('/login', methods=['POST'])\\ndef login(): ...",
        "others": [
            "request.form / request.args / request.json read input",
            "render_template('x.html', **ctx) renders a Jinja2 template",
            "redirect(url_for('view')) builds URLs from view names",
            "Blueprints split a large app into pluggable sub-apps",
        ],
    },
    "flask_login": {
        "why": "Session-based authentication for Flask — user loader, "
               "@login_required, current_user proxy.",
        "example": "@login_required\\ndef dashboard(): ...",
        "others": [
            "login_user(user) / logout_user() set the session cookie",
            "current_user is a proxy that resolves per-request",
        ],
    },
    "flask_limiter": {
        "why": "Per-route rate limiting for Flask — protects login pages "
               "and ingestion endpoints from brute force / abuse.",
        "example": "@limiter.limit('5/minute')\\ndef login(): ...",
        "others": [
            "Default keying is by remote IP",
            "Override key_func to limit by user id or API key",
        ],
    },
    "sqlalchemy": {
        "why": "Python's most popular ORM and SQL toolkit. Models declare "
               "tables as classes; the engine handles connection pooling.",
        "example": "session.query(User).filter_by(email=e).first()",
        "others": [
            "Column / relationship / ForeignKey declare schema",
            "session.add(obj); session.commit()",
            "with engine.begin() as conn: conn.execute(text('SQL'))",
            "2.0-style: select(User).where(User.id == 1)",
        ],
    },
    "alembic": {
        "why": "Migration framework that pairs with SQLAlchemy. Each "
               "version file describes a forward + rollback step.",
        "example": "alembic upgrade head  # apply all pending migrations",
        "others": [
            "alembic revision --autogenerate -m 'msg' diffs models vs DB",
            "op.add_column / op.drop_column / op.alter_column inside a version",
        ],
    },
    "psycopg2": {
        "why": "PostgreSQL driver. Used directly for raw SQL paths and as "
               "the dialect SQLAlchemy talks through.",
        "example": "psycopg2.connect(dsn)",
        "others": [
            "Always use parameterised queries: cur.execute('... WHERE id=%s', (id,))",
            "psycopg2.extras.RealDictCursor returns dict-like rows",
            "On 3+ the modern replacement is psycopg (psycopg3)",
        ],
    },
    "pandas": {
        "why": "DataFrame library — the workhorse for tabular data: "
               "loading CSV/Excel/SQL, joins, aggregations, time-series.",
        "example": "df = pd.read_csv(path); df.groupby('symbol')['pnl'].sum()",
        "others": [
            "df.merge(other, on='key') joins like SQL",
            "df.resample('1D').agg(...) for time-series rebucketing",
            "df.to_sql / df.to_excel / df.to_parquet for output",
            "df.loc[mask, 'col'] for label-based selection/assignment",
        ],
    },
    "numpy": {
        "why": "N-dimensional arrays — vectorised numerical computation. "
               "Backs pandas; used directly for indicator math.",
        "example": "np.where(close > open, 1, -1)  # vectorised conditional",
        "others": [
            "Broadcasting: arr * scalar, arr + arr2 work element-wise",
            "np.nan / np.isnan(x) for missing values",
            "np.array(list) creates a typed array; choose dtype carefully",
        ],
    },
    "MetaTrader5": {
        "why": "Official MetaQuotes Python API for MT5. Connects to a "
               "local terminal, places orders, reads tick/bar history.",
        "example": "mt5.initialize(); mt5.order_send(request)",
        "others": [
            "mt5.symbols_get() / mt5.symbol_info(symbol)",
            "mt5.history_deals_get(from_, to_) returns closed deals",
            "mt5.account_info() returns balance/equity/currency",
            "Always mt5.shutdown() in a finally to release the terminal",
        ],
    },
    "selenium": {
        "why": "Browser automation. Drives a real Chrome instance — the "
               "fallback for scraping prop-firm dashboards that have no "
               "API.",
        "example": "driver.get(url); driver.find_element(By.ID, 'login')",
        "others": [
            "WebDriverWait + expected_conditions for reliable waits",
            "ChromeOptions().add_argument('--headless=new')",
            "execute_script(js, *args) reaches into the page for things "
            "the DOM API can't express",
        ],
    },
    "apscheduler": {
        "why": "In-process cron-style job scheduler. Runs the dashboard's "
               "periodic resync, payout-calculation, and notification "
               "jobs.",
        "example": "scheduler.add_job(resync, 'cron', hour=2, minute=0)",
        "others": [
            "BackgroundScheduler / BlockingScheduler differ in whether they "
            "hold the main thread",
            "Triggers: date / interval / cron",
            "Add a JobStore (SQLAlchemy) to survive restarts",
        ],
    },
    "werkzeug": {
        "why": "WSGI utility library that Flask is built on. Mostly used "
               "directly for security helpers (password hashing) and "
               "exception classes.",
        "example": "generate_password_hash(pwd) / check_password_hash(h, pwd)",
        "others": [
            "werkzeug.exceptions.Forbidden / NotFound for HTTP errors",
            "secure_filename() sanitises uploaded filenames",
        ],
    },
    "bcrypt": {
        "why": "Password hashing using bcrypt — slow, salted, "
               "purpose-built. The right tool for storing user passwords.",
        "example": "bcrypt.hashpw(pwd.encode(), bcrypt.gensalt())",
        "others": [
            "bcrypt.checkpw(plain.encode(), hashed) returns a bool",
            "Tune the cost factor with rounds= as hardware improves",
        ],
    },
    "dotenv": {
        "why": "python-dotenv — load .env files into os.environ for "
               "twelve-factor configuration in development.",
        "example": "load_dotenv()  # call once at process start",
        "others": [
            "dotenv_values('.env') returns a dict without polluting os.environ",
            "Use a real secret store in production (vault, AWS SM, etc.)",
        ],
    },
    "gspread": {
        "why": "Google Sheets API client. Reads/writes the dashboard's "
               "source-of-truth spreadsheets.",
        "example": "client.open('Trades').sheet1.get_all_records()",
        "others": [
            "worksheet.update('A1', [[...]]) writes a 2-D block",
            "batch_update minimises API quota usage",
        ],
    },
    "reportlab": {
        "why": "PDF generation. The library this very book is built with — "
               "and the same one used elsewhere in the codebase to render "
               "the client pitch and quality roadmap PDFs.",
        "example": "BaseDocTemplate(out, pagesize=LETTER).build([flowables])",
        "others": [
            "Paragraph / Preformatted / Table / Image are flowables",
            "ParagraphStyle controls font, size, leading, colour, alignment",
            "Page-level drawing goes in an onPage canvas callback",
        ],
    },
    "openpyxl": {
        "why": "Read/write modern Excel .xlsx files (the format MT5 export "
               "history is delivered in).",
        "example": "wb = load_workbook(path); ws = wb.active; ws['A1'].value",
        "others": [
            "ws.iter_rows(values_only=True) for fast row iteration",
            "wb.save(path) to write back",
        ],
    },
    "bs4": {
        "why": "BeautifulSoup — HTML parser. Pulls structured data out of "
               "pages that don't expose an API.",
        "example": "BeautifulSoup(html, 'lxml').select('div.price')",
        "others": [
            "soup.find_all(name, attrs={'class': 'x'})",
            "Specify a parser ('lxml', 'html.parser') for predictable behaviour",
        ],
    },
    "cryptography": {
        "why": "Modern crypto primitives — Fernet for symmetric encryption, "
               "x509 for certificates, RSA/ECDSA for asymmetric.",
        "example": "Fernet(key).encrypt(b'secret')",
        "others": [
            "Fernet.generate_key() returns a 32-byte url-safe key",
            "Pin the library version — crypto APIs evolve",
        ],
    },
    "jwt": {
        "why": "PyJWT — encode/decode JSON Web Tokens for API "
               "authentication.",
        "example": "jwt.encode({'sub': uid}, key, algorithm='HS256')",
        "others": [
            "Always specify algorithms= on decode (never accept 'none')",
            "exp/iat/nbf claims are validated automatically",
        ],
    },
    "pychrome": {
        "why": "Chrome DevTools Protocol client — attaches to a running "
               "Chrome instance to read network traffic. The deeper "
               "alternative when Selenium can't see the data.",
        "example": "browser = pychrome.Browser(url='http://127.0.0.1:9222')",
        "others": [
            "tab.Network.requestWillBeSent intercepts outgoing requests",
            "Useful when the page renders data via XHR you want to capture",
        ],
    },
}


# Local in-repo packages that show up as imports
LOCAL_KB: dict[str, str] = {
    "trader_companion": "Internal package — the desktop trader companion. "
                          "See chapter on trader_companion/.",
    "dashboard": "Internal package — the Flask dashboard. See chapter on "
                  "dashboard/.",
    "connectors": "Internal package — MetaTrader 5 connection wrappers. "
                    "See chapter on connectors/.",
    "config": "Internal package — application settings and the firm "
                "hierarchy.",
    "utils": "Internal package — shared helpers used across the app.",
    "signals": "Sub-package of trader_companion — one technical indicator "
                 "per file.",
    "strategies": "Sub-package of trader_companion — composed indicator "
                    "strategies.",
    "watermark_service": "Sibling module — high-water-mark accounting.",
    "database": "Sibling module — engine and session factory.",
    "prop_firm_manager": "Sibling module — coordinates the per-firm scrapers.",
    "chrome_auto_compatibility": "Sibling module — Chrome / chromedriver "
                                   "version matching helper.",
    "models": "Sibling module — SQLAlchemy ORM models.",
}


def kb_lookup(top: str) -> dict | None:
    if top in MODULE_KB:
        return MODULE_KB[top]
    if top in LOCAL_KB:
        return {"why": LOCAL_KB[top], "example": None, "others": []}
    return None


# ---------------------------------------------------------------------------
# 1b.  Detect actual import usage in a module
# ---------------------------------------------------------------------------


def collect_import_usage(tree: ast.AST) -> tuple[dict, dict, dict, dict]:
    """Walk the tree and return:

    - alias_to_module:  e.g., 'np' -> 'numpy', 'os' -> 'os'
    - from_alias:       e.g., 'join' -> ('os.path', 'join')
    - used_attrs:       module-name -> set of dotted-attrs accessed
    - used_from_names:  module-name -> set of from-imported names referenced
    """
    alias_to_module: dict[str, str] = {}
    from_alias: dict[str, tuple[str, str]] = {}

    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for n in node.names:
                alias = n.asname or n.name.split(".")[0]
                alias_to_module[alias] = n.name
        elif isinstance(node, ast.ImportFrom):
            mod = node.module or ""
            for n in node.names:
                alias = n.asname or n.name
                from_alias[alias] = (mod, n.name)

    used_attrs: dict[str, set[str]] = defaultdict(set)
    used_from_names: dict[str, set[str]] = defaultdict(set)

    for node in ast.walk(tree):
        if isinstance(node, ast.Attribute):
            # Walk down to the leftmost Name, accumulating attrs.
            attrs: list[str] = [node.attr]
            cur = node.value
            while isinstance(cur, ast.Attribute):
                attrs.append(cur.attr)
                cur = cur.value
            if isinstance(cur, ast.Name) and cur.id in alias_to_module:
                mod = alias_to_module[cur.id]
                # The first attr in display order is the topmost (last seen)
                attrs.reverse()
                # We only show 1-2 levels deep so it stays readable
                used_attrs[mod].add(".".join(attrs[:2]))
        elif isinstance(node, ast.Name) and node.id in from_alias:
            mod, original = from_alias[node.id]
            used_from_names[mod].add(original)

    return alias_to_module, from_alias, used_attrs, used_from_names


def build_import_records(tree: ast.AST) -> list[dict]:
    """Build a list of per-import records ready for rendering.

    Each record has:
      - line:  the original import statement (string)
      - top:   the top-level module name (used to look up KB entries)
      - kind:  'import' or 'from'
      - used:  list of strings — actual usages detected in this file
      - kb:    KB entry (or None)
    """
    _, _, used_attrs, used_from_names = collect_import_usage(tree)
    records: list[dict] = []

    for node in tree.body:
        if isinstance(node, ast.Import):
            for n in node.names:
                top = n.name.split(".")[0]
                line = f"import {n.name}"
                if n.asname:
                    line += f" as {n.asname}"
                base = n.asname or top
                # Usages keyed by the full dotted module name we stored
                # under alias_to_module
                key = n.name
                used = sorted(used_attrs.get(key, set()))
                # Render usage as alias.attr
                used_disp = [f"{base}.{a}" for a in used][:8]
                records.append({
                    "line": line,
                    "top": top,
                    "full": n.name,
                    "kind": "import",
                    "used": used_disp,
                    "kb": kb_lookup(top),
                })
        elif isinstance(node, ast.ImportFrom):
            mod = ("." * node.level) + (node.module or "")
            top = (node.module or "").split(".")[0] if node.module else ""
            for n in node.names:
                line = f"from {mod} import {n.name}"
                if n.asname:
                    line += f" as {n.asname}"
                used = []
                full_mod_for_lookup = node.module or ""
                # Match against used_from_names keyed by full module
                if n.name in used_from_names.get(full_mod_for_lookup, set()):
                    used.append(n.asname or n.name)
                records.append({
                    "line": line,
                    "top": top,
                    "full": full_mod_for_lookup,
                    "kind": "from",
                    "used": used,
                    "kb": kb_lookup(top) if top else None,
                })
        # We deliberately skip non-import top-level statements here

    return records


# ---------------------------------------------------------------------------
# 2a.  Per-function "why this concept was used" analysis
# ---------------------------------------------------------------------------


def _short_unparse(node: ast.AST, limit: int = 50) -> str:
    try:
        s = ast.unparse(node)
    except Exception:
        return "?"
    s = s.replace("\n", " ")
    if len(s) > limit:
        s = s[: limit - 3] + "..."
    return s


def analyze_function(node: ast.FunctionDef | ast.AsyncFunctionDef) -> list[tuple[str, str]]:
    """Return a list of (concept-name, rationale) pairs for this function.

    Each entry explains *why* a particular Python feature was used in the
    body or signature of this specific function. The output is rendered in
    the PDF under a "Why these concepts were used" block per function.
    """
    pairs: list[tuple[str, str]] = []

    # ---- async ------------------------------------------------------------
    if isinstance(node, ast.AsyncFunctionDef):
        pairs.append((
            "async def",
            "Declared with <b>async def</b> so it returns a coroutine. "
            "The body is paused on each <b>await</b>, freeing the event "
            "loop to run other coroutines while this one waits on slow "
            "I/O — useful when many calls are outbound HTTP, websocket, "
            "or database round trips.",
        ))

    # ---- decorators -------------------------------------------------------
    for d in node.decorator_list:
        try:
            full = ast.unparse(d)
        except Exception:
            full = "?"
        head = full.split("(")[0].strip()
        if head == "property":
            pairs.append((
                "@property",
                "Wrapped in <b>@property</b> so callers access the value "
                "with attribute syntax (<code>obj.x</code>) instead of a "
                "method call. Lets the implementation compute or validate "
                "the value lazily without changing the call site.",
            ))
        elif head == "classmethod":
            pairs.append((
                "@classmethod",
                "Marked <b>@classmethod</b> — receives the class itself "
                "as the first argument. The standard pattern for "
                "alternate constructors that build an instance from a "
                "different input shape (e.g., from a dict, a CSV row, or "
                "an MT5 order tuple).",
            ))
        elif head == "staticmethod":
            pairs.append((
                "@staticmethod",
                "Declared <b>@staticmethod</b> because the function "
                "logically belongs in this class's namespace but does "
                "not depend on either the instance or the class — it is "
                "a pure helper that happens to be co-located with "
                "related code.",
            ))
        elif "abstractmethod" in head:
            pairs.append((
                f"@{head}",
                "Marked abstract — concrete subclasses must override it, "
                "or instantiating them raises TypeError. Used to encode "
                "an interface contract in the type itself instead of "
                "relying on documentation.",
            ))
        elif "route" in head or head.endswith(".get") or head.endswith(".post"):
            pairs.append((
                f"@{head}",
                "Registers this function as a Flask URL handler. The "
                "decorator binds the URL pattern (and optional HTTP "
                "methods) to the function so Flask can dispatch incoming "
                "requests here.",
            ))
        elif "login_required" in head or "requires_" in head or "_required" in head:
            pairs.append((
                f"@{head}",
                "An auth/role gate. Wraps the request handler so that "
                "callers without the right session or permission get "
                "redirected (or a 401/403) before the body runs.",
            ))
        elif "lru_cache" in head or "cache" in head:
            pairs.append((
                f"@{head}",
                "Memoises return values keyed by the arguments. Trades "
                "memory for speed when the function is pure and called "
                "many times with the same inputs.",
            ))
        elif head == "contextmanager" or head.endswith(".contextmanager"):
            pairs.append((
                f"@{head}",
                "Turns a generator (which <b>yield</b>s exactly once) "
                "into a context manager — the code before the yield "
                "runs on enter, the code after runs on exit. A concise "
                "alternative to writing __enter__/__exit__ by hand.",
            ))
        elif head == "dataclass" or head.endswith(".dataclass"):
            pairs.append((
                f"@{head}",
                "Auto-generates __init__/__repr__/__eq__ from the "
                "annotated fields. Removes the boilerplate that "
                "\"plain data\" classes would otherwise need.",
            ))
        elif head not in ("property", "classmethod", "staticmethod"):
            pairs.append((
                f"@{head}",
                "Decorator applied to the function — wraps it so that "
                "extra behaviour runs around each call without changing "
                "the call site.",
            ))

    # ---- type hints -------------------------------------------------------
    typed_args = [
        a for a in node.args.args + node.args.kwonlyargs + node.args.posonlyargs
        if a.annotation is not None
    ]
    if typed_args:
        sample = ", ".join(
            f"{a.arg}: {_short_unparse(a.annotation, 28)}" for a in typed_args[:3]
        )
        pairs.append((
            "type-annotated parameters",
            f"Parameters carry type hints (e.g., <code>{esc(sample)}</code>). "
            "Hints are not enforced at runtime — they document intent for "
            "static checkers (mypy/pyright), IDE auto-complete, and human "
            "readers. They are the fastest way to make a public function "
            "self-explanatory.",
        ))
    if node.returns is not None:
        rtn = _short_unparse(node.returns, 40)
        pairs.append((
            "return type annotation",
            f"Annotated return type <code>-&gt; {esc(rtn)}</code>. "
            "Declares the function's contract: callers can rely on this "
            "shape, and tools can flag a caller that misuses the result.",
        ))

    # ---- *args / **kwargs -------------------------------------------------
    if node.args.vararg is not None:
        pairs.append((
            f"*{node.args.vararg.arg}",
            "Accepts a variable number of positional arguments. Most "
            "common reason: the function forwards them to another "
            "callable, or it operates on a list whose length is not "
            "fixed up front.",
        ))
    if node.args.kwarg is not None:
        pairs.append((
            f"**{node.args.kwarg.arg}",
            "Accepts arbitrary keyword arguments. Usually for "
            "forwarding to another function (a thin wrapper) or to "
            "support optional named parameters without listing them "
            "all in the signature.",
        ))
    if node.args.kwonlyargs:
        names = ", ".join(a.arg for a in node.args.kwonlyargs[:4])
        pairs.append((
            "keyword-only parameters",
            f"Parameters after the bare <code>*</code> "
            f"(<code>{esc(names)}</code>) must be passed by name. "
            "Forces callers to spell out what they mean — a guard "
            "against accidentally passing positional arguments in the "
            "wrong order.",
        ))

    # ---- body walk --------------------------------------------------------
    saw = {
        "yield": False,
        "yield_from": False,
        "await": False,
        "try": False,
        "with": False,
        "async_with": False,
        "list_comp": False,
        "set_comp": False,
        "dict_comp": False,
        "gen_exp": False,
        "lambda": False,
        "fstring": False,
        "raise": False,
        "isinstance": False,
        "walrus": False,
        "assert": False,
        "match": False,
        "global": False,
        "nonlocal": False,
        "nested_def": False,
        "for_loop": False,
        "while_loop": False,
        "ternary": False,
        "ctx_mgr_dunder": node.name in ("__enter__", "__exit__", "__aenter__", "__aexit__"),
        "iter_dunder": node.name in ("__iter__", "__next__"),
        "call_dunder": node.name == "__call__",
        "init": node.name == "__init__",
        "repr": node.name in ("__repr__", "__str__"),
        "eq": node.name in ("__eq__", "__hash__"),
        "getitem": node.name in ("__getitem__", "__setitem__", "__delitem__"),
        "len": node.name == "__len__",
    }

    for sub in ast.walk(node):
        if sub is node:
            continue
        if isinstance(sub, (ast.FunctionDef, ast.AsyncFunctionDef)):
            saw["nested_def"] = True
            continue  # don't peer inside a nested function
        if isinstance(sub, ast.Yield):
            saw["yield"] = True
        if isinstance(sub, ast.YieldFrom):
            saw["yield_from"] = True
        if isinstance(sub, ast.Await):
            saw["await"] = True
        if isinstance(sub, ast.Try):
            saw["try"] = True
        if isinstance(sub, ast.With):
            saw["with"] = True
        if isinstance(sub, ast.AsyncWith):
            saw["async_with"] = True
        if isinstance(sub, ast.ListComp):
            saw["list_comp"] = True
        if isinstance(sub, ast.SetComp):
            saw["set_comp"] = True
        if isinstance(sub, ast.DictComp):
            saw["dict_comp"] = True
        if isinstance(sub, ast.GeneratorExp):
            saw["gen_exp"] = True
        if isinstance(sub, ast.Lambda):
            saw["lambda"] = True
        if isinstance(sub, ast.JoinedStr):
            saw["fstring"] = True
        if isinstance(sub, ast.Raise):
            saw["raise"] = True
        if isinstance(sub, ast.Assert):
            saw["assert"] = True
        if isinstance(sub, ast.NamedExpr):
            saw["walrus"] = True
        if isinstance(sub, ast.Match):
            saw["match"] = True
        if isinstance(sub, ast.Global):
            saw["global"] = True
        if isinstance(sub, ast.Nonlocal):
            saw["nonlocal"] = True
        if isinstance(sub, ast.For):
            saw["for_loop"] = True
        if isinstance(sub, ast.While):
            saw["while_loop"] = True
        if isinstance(sub, ast.IfExp):
            saw["ternary"] = True
        if isinstance(sub, ast.Call):
            try:
                fname = ast.unparse(sub.func)
            except Exception:
                fname = ""
            if fname == "isinstance":
                saw["isinstance"] = True

    if saw["yield"] or saw["yield_from"]:
        pairs.append((
            "generator (yield)",
            "The body uses <b>yield</b>, so calling it returns an "
            "iterator instead of a value. Items are produced lazily — "
            "the function only runs as far as the next <b>yield</b> on "
            "each iteration. Right choice when the caller iterates "
            "results and the dataset is large or open-ended.",
        ))
    if saw["yield_from"]:
        pairs.append((
            "yield from",
            "Delegates iteration to another iterable. Equivalent to a "
            "loop that yields each item, but shorter and forwards "
            "<code>send</code>/<code>throw</code> to the inner generator.",
        ))
    if saw["await"] and not isinstance(node, ast.AsyncFunctionDef):
        pairs.append((
            "await (in async block)",
            "Uses <b>await</b> inside an async helper or comprehension.",
        ))
    if saw["try"]:
        pairs.append((
            "try/except",
            "Wraps part of the body in <b>try/except</b>. The function "
            "expects a particular failure mode (network timeout, missing "
            "file, parse error) and either recovers or returns a "
            "fallback so the caller doesn't have to handle it.",
        ))
    if saw["with"]:
        pairs.append((
            "with-statement",
            "Uses a <b>with</b> block, so the resource (file, lock, "
            "transaction, MT5 session) is released even if the body "
            "raises. Avoids the easy bug of a missed close on the error "
            "path.",
        ))
    if saw["async_with"]:
        pairs.append((
            "async with",
            "Acquires/releases an async resource (e.g., aiohttp session) "
            "around an awaitable block.",
        ))
    if saw["list_comp"]:
        pairs.append((
            "list comprehension",
            "Builds a list in a single expression "
            "(<code>[f(x) for x in xs]</code>). Faster than the "
            "equivalent for-loop with append, and clearer about intent: "
            "this is a transform, not a side-effecting loop.",
        ))
    if saw["dict_comp"]:
        pairs.append((
            "dict comprehension",
            "Builds a dict in one expression "
            "(<code>{k: v for k, v in items}</code>) — same intent "
            "as a list comprehension but for mappings.",
        ))
    if saw["set_comp"]:
        pairs.append((
            "set comprehension",
            "Builds a set in one expression — usually to deduplicate "
            "the result of a transform.",
        ))
    if saw["gen_exp"]:
        pairs.append((
            "generator expression",
            "Uses a generator expression (parentheses, not square "
            "brackets) — the items are produced lazily. Common as the "
            "argument to <code>sum</code>, <code>any</code>, "
            "<code>all</code>, or <code>max</code> where the "
            "intermediate list would be wasted.",
        ))
    if saw["lambda"]:
        pairs.append((
            "lambda",
            "Uses a single-expression anonymous function — typically as "
            "the <code>key=</code> for a sort, the <code>filter</code> "
            "predicate, or a small callback.",
        ))
    if saw["fstring"]:
        pairs.append((
            "f-string",
            "Builds strings with <b>f-strings</b>. Compiled at parse "
            "time — the fastest formatting option, and the format spec "
            "after the colon controls width, precision, and alignment.",
        ))
    if saw["raise"]:
        pairs.append((
            "raise",
            "Raises an exception explicitly. Either signals an invalid "
            "argument the caller should fix, or re-raises after logging.",
        ))
    if saw["assert"]:
        pairs.append((
            "assert",
            "Uses <b>assert</b> to check an invariant. Note: assertions "
            "are removed when Python is run with <code>-O</code>, so "
            "they should encode developer expectations, not runtime "
            "user-input validation.",
        ))
    if saw["isinstance"]:
        pairs.append((
            "isinstance check",
            "Branches on the runtime type of a value. Used when a "
            "function accepts more than one input shape (e.g., a string "
            "or a list of strings) and needs to handle each.",
        ))
    if saw["walrus"]:
        pairs.append((
            "walrus operator (:=)",
            "Assigns and tests in one expression — typically inside a "
            "while or if to capture a regex match or a non-None lookup "
            "without an extra line.",
        ))
    if saw["match"]:
        pairs.append((
            "match / case",
            "Structural pattern matching. Cleaner than chained "
            "isinstance/elif when dispatching on the shape of a value.",
        ))
    if saw["nested_def"]:
        pairs.append((
            "nested function",
            "Defines a function inside this function. Usually a closure "
            "that captures local variables, or a callback passed to "
            "another function.",
        ))
    if saw["nonlocal"]:
        pairs.append((
            "nonlocal",
            "Declares a name as belonging to an enclosing function's "
            "scope. The flag that says <i>this nested function is "
            "rebinding the outer variable, not creating its own</i>.",
        ))
    if saw["global"]:
        pairs.append((
            "global",
            "Rebinds a module-level name from inside the function. A "
            "smell in larger codebases — usually means a singleton or "
            "cache that could be passed in instead.",
        ))
    if saw["ternary"]:
        pairs.append((
            "ternary expression",
            "Uses <code>x if cond else y</code> — a conditional "
            "expression, not a statement. Right tool when both branches "
            "produce a value the surrounding expression consumes.",
        ))

    # Dunder-method rationales
    if saw["init"]:
        pairs.append((
            "__init__",
            "The constructor. Runs after Python has allocated the "
            "instance; assigns starting attribute values to "
            "<code>self</code>.",
        ))
    if saw["repr"]:
        name = "__repr__" if node.name == "__repr__" else "__str__"
        pairs.append((
            name,
            f"Defines <b>{name}</b> so the instance has a useful string "
            "representation in logs, the REPL, and error messages.",
        ))
    if saw["eq"]:
        pairs.append((
            f"{node.name}",
            "Implements value-based equality (or hashability). Two "
            "instances compare equal when their meaningful fields match, "
            "not just when they are the same object in memory.",
        ))
    if saw["getitem"]:
        pairs.append((
            f"{node.name}",
            "Hooks into subscript syntax (<code>obj[key]</code>). The "
            "class behaves like a mapping or sequence at the call site.",
        ))
    if saw["len"]:
        pairs.append((
            "__len__",
            "Defines <b>__len__</b> so <code>len(obj)</code> works and "
            "the class is truthy/falsy by length.",
        ))
    if saw["iter_dunder"]:
        pairs.append((
            f"{node.name}",
            "Makes instances iterable — usable directly in a "
            "<code>for</code> loop or anywhere an iterator is expected.",
        ))
    if saw["call_dunder"]:
        pairs.append((
            "__call__",
            "Makes instances callable — <code>obj(args)</code> dispatches "
            "into this method. Useful for stateful callables and for "
            "writing classes that act like functions.",
        ))
    if saw["ctx_mgr_dunder"]:
        pairs.append((
            f"{node.name}",
            "Half of the context-manager protocol. Pairs with its "
            "sibling so the class can be used in a <b>with</b> "
            "statement; <b>__enter__</b> sets up, <b>__exit__</b> tears "
            "down regardless of how the block ends.",
        ))

    return pairs


# ---------------------------------------------------------------------------
# 2b.  Per-function step-by-step (top-level body walkthrough)
# ---------------------------------------------------------------------------


def _describe_stmt(stmt: ast.AST) -> str:
    """One-line plain-English description of a top-level statement."""
    if isinstance(stmt, ast.Expr) and isinstance(stmt.value, ast.Constant) and isinstance(stmt.value.value, str):
        return "Module/function docstring."
    if isinstance(stmt, ast.Assign):
        try:
            tgts = ", ".join(ast.unparse(t) for t in stmt.targets)
            val = _short_unparse(stmt.value, 60)
            return f"Assigns <code>{esc(tgts)}</code> = <code>{esc(val)}</code>."
        except Exception:
            return "Assigns to one or more local names."
    if isinstance(stmt, ast.AnnAssign):
        try:
            tgt = ast.unparse(stmt.target)
            ann = ast.unparse(stmt.annotation)
            if stmt.value is not None:
                val = _short_unparse(stmt.value, 50)
                return f"Declares <code>{esc(tgt)}: {esc(ann)}</code> = <code>{esc(val)}</code>."
            return f"Declares <code>{esc(tgt)}: {esc(ann)}</code> (annotation only)."
        except Exception:
            return "Annotated assignment."
    if isinstance(stmt, ast.AugAssign):
        try:
            tgt = ast.unparse(stmt.target)
            op = type(stmt.op).__name__
            return f"Updates <code>{esc(tgt)}</code> in place ({op})."
        except Exception:
            return "Updates a name in place."
    if isinstance(stmt, ast.If):
        try:
            cond = _short_unparse(stmt.test, 70)
        except Exception:
            cond = "..."
        s = f"<b>if</b> <code>{esc(cond)}</code>: branches conditionally"
        if stmt.orelse:
            s += " (with an <b>else</b>/elif arm)"
        return s + "."
    if isinstance(stmt, ast.For):
        try:
            tgt = ast.unparse(stmt.target)
            it = _short_unparse(stmt.iter, 60)
        except Exception:
            tgt, it = "...", "..."
        return f"<b>for</b> <code>{esc(tgt)}</code> in <code>{esc(it)}</code>: iterates."
    if isinstance(stmt, ast.AsyncFor):
        try:
            tgt = ast.unparse(stmt.target)
            it = _short_unparse(stmt.iter, 60)
        except Exception:
            tgt, it = "...", "..."
        return f"<b>async for</b> <code>{esc(tgt)}</code> in <code>{esc(it)}</code>: iterates an async source."
    if isinstance(stmt, ast.While):
        try:
            cond = _short_unparse(stmt.test, 70)
        except Exception:
            cond = "..."
        return f"<b>while</b> <code>{esc(cond)}</code>: loops until the condition is false."
    if isinstance(stmt, ast.Try):
        n_handlers = len(stmt.handlers)
        has_finally = bool(stmt.finalbody)
        bits = [f"<b>try</b> block with {n_handlers} <b>except</b> clause"
                + ("s" if n_handlers != 1 else "")]
        if has_finally:
            bits.append("plus a <b>finally</b>")
        return ", ".join(bits) + "."
    if isinstance(stmt, ast.With):
        items = []
        for it in stmt.items:
            try:
                items.append(ast.unparse(it.context_expr))
            except Exception:
                items.append("...")
        items_s = ", ".join(items[:3])
        return f"<b>with</b> <code>{esc(items_s)}</code>: enters a context manager."
    if isinstance(stmt, ast.AsyncWith):
        return "<b>async with</b>: enters an async context manager."
    if isinstance(stmt, ast.Return):
        if stmt.value is None:
            return "<b>return</b> (no value — returns None)."
        try:
            val = _short_unparse(stmt.value, 70)
        except Exception:
            val = "..."
        return f"<b>return</b> <code>{esc(val)}</code>."
    if isinstance(stmt, ast.Raise):
        try:
            exc = _short_unparse(stmt.exc, 70) if stmt.exc else "(re-raise)"
        except Exception:
            exc = "..."
        return f"<b>raise</b> <code>{esc(exc)}</code>."
    if isinstance(stmt, ast.Assert):
        try:
            test = _short_unparse(stmt.test, 70)
        except Exception:
            test = "..."
        return f"<b>assert</b> <code>{esc(test)}</code>."
    if isinstance(stmt, ast.Expr):
        if isinstance(stmt.value, ast.Call):
            try:
                fname = ast.unparse(stmt.value.func)
            except Exception:
                fname = "?"
            return f"Calls <code>{esc(fname)}(...)</code> for its side effect."
        if isinstance(stmt.value, ast.Yield):
            try:
                v = _short_unparse(stmt.value.value, 70) if stmt.value.value else "None"
            except Exception:
                v = "..."
            return f"<b>yield</b> <code>{esc(v)}</code>: produces a value to the iterator consumer."
        if isinstance(stmt.value, ast.YieldFrom):
            try:
                v = _short_unparse(stmt.value.value, 70)
            except Exception:
                v = "..."
            return f"<b>yield from</b> <code>{esc(v)}</code>: delegates iteration to another iterable."
        if isinstance(stmt.value, ast.Await):
            try:
                v = _short_unparse(stmt.value.value, 70)
            except Exception:
                v = "..."
            return f"<b>await</b> <code>{esc(v)}</code>: pauses until the awaitable resolves."
        return "Expression statement (called for its side effect)."
    if isinstance(stmt, ast.Pass):
        return "<b>pass</b> (placeholder)."
    if isinstance(stmt, ast.Break):
        return "<b>break</b>: exits the enclosing loop."
    if isinstance(stmt, ast.Continue):
        return "<b>continue</b>: skips to the next iteration."
    if isinstance(stmt, ast.Global):
        return f"Declares globals: {esc(', '.join(stmt.names))}."
    if isinstance(stmt, ast.Nonlocal):
        return f"Declares nonlocals: {esc(', '.join(stmt.names))}."
    if isinstance(stmt, ast.FunctionDef):
        return f"Defines a nested function <code>{esc(stmt.name)}(...)</code>."
    if isinstance(stmt, ast.AsyncFunctionDef):
        return f"Defines a nested async function <code>{esc(stmt.name)}(...)</code>."
    if isinstance(stmt, ast.ClassDef):
        return f"Defines a nested class <code>{esc(stmt.name)}</code>."
    if isinstance(stmt, ast.Import):
        names = ", ".join(n.name for n in stmt.names)
        return f"Imports <code>{esc(names)}</code> (lazy import inside the function)."
    if isinstance(stmt, ast.ImportFrom):
        return f"Lazy import from <code>{esc(stmt.module or '')}</code>."
    if isinstance(stmt, ast.Match):
        return "<b>match</b> statement: dispatches on the shape of a value."
    return f"{type(stmt).__name__} statement."


def describe_steps(node: ast.FunctionDef | ast.AsyncFunctionDef, max_steps: int = 14) -> list[str]:
    body = list(node.body)
    if body and isinstance(body[0], ast.Expr) and isinstance(body[0].value, ast.Constant) and isinstance(body[0].value.value, str):
        body = body[1:]  # skip docstring
    steps: list[str] = []
    for i, stmt in enumerate(body):
        if i >= max_steps:
            steps.append(f"<i>... and {len(body) - max_steps} more statement(s) in the body.</i>")
            break
        steps.append(_describe_stmt(stmt))
    return steps


def detect_features(tree: ast.AST) -> set[str]:
    """Detect which Python language features appear in the module."""
    feats: set[str] = set()
    has_typed_arg = False
    has_typed_return = False
    has_typed_assign = False

    for node in ast.walk(tree):
        if isinstance(node, ast.AsyncFunctionDef):
            feats.add("async")
        if isinstance(node, (ast.AsyncFor, ast.AsyncWith)):
            feats.add("async")
        if isinstance(node, ast.Await):
            feats.add("async")
        if isinstance(node, (ast.Yield, ast.YieldFrom)):
            feats.add("generators")
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            for d in getattr(node, "decorator_list", []):
                feats.add("decorators")
                try:
                    name = ast.unparse(d).split("(")[0].strip()
                except Exception:
                    name = ""
                if name == "property":
                    feats.add("properties")
                if name in ("staticmethod", "classmethod"):
                    feats.add("classmethod_staticmethod")
                if name == "dataclass" or name.endswith(".dataclass"):
                    feats.add("dataclasses")
                if name == "contextmanager" or name.endswith(".contextmanager"):
                    feats.add("context_managers")
                if name == "abstractmethod" or name.endswith(".abstractmethod"):
                    feats.add("abstract_classes")
                if name in ("app.route", "app.get", "app.post") or "route" in name:
                    feats.add("flask_routes")
        if isinstance(node, ast.With):
            feats.add("context_managers")
        if isinstance(node, (ast.ListComp, ast.SetComp, ast.DictComp, ast.GeneratorExp)):
            feats.add("comprehensions")
        if isinstance(node, ast.Lambda):
            feats.add("lambdas")
        if isinstance(node, ast.Try):
            feats.add("exceptions")
        if isinstance(node, ast.Raise):
            feats.add("exceptions")
        if isinstance(node, ast.JoinedStr):
            feats.add("fstrings")
        if isinstance(node, ast.NamedExpr):
            feats.add("walrus")
        if isinstance(node, ast.Match):
            feats.add("match_case")
        if isinstance(node, ast.ClassDef):
            feats.add("classes")
            if any(
                isinstance(b, ast.Name) and b.id == "Exception" or
                (isinstance(b, ast.Attribute) and b.attr == "Exception")
                for b in node.bases
            ):
                feats.add("custom_exceptions")
            for b in node.bases:
                try:
                    bname = ast.unparse(b)
                except Exception:
                    bname = ""
                if bname in ("ABC", "abc.ABC"):
                    feats.add("abstract_classes")
                if "Enum" in bname:
                    feats.add("enums")
                if bname == "TypedDict" or bname.endswith(".TypedDict"):
                    feats.add("typed_dict")
                if bname == "NamedTuple" or bname.endswith(".NamedTuple"):
                    feats.add("named_tuple")
                if "BaseModel" in bname:
                    feats.add("pydantic")
                if "Model" in bname or "db.Model" in bname:
                    feats.add("orm_model")
            if node.bases and not any(
                ast.unparse(b) in ("object",) for b in node.bases if hasattr(ast, "unparse")
            ):
                feats.add("inheritance")
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            for a in node.args.args + node.args.kwonlyargs + node.args.posonlyargs:
                if a.annotation is not None:
                    has_typed_arg = True
            if node.returns is not None:
                has_typed_return = True
            if node.name in ("__enter__", "__exit__", "__aenter__", "__aexit__"):
                feats.add("context_managers")
            if node.name in (
                "__init__", "__repr__", "__str__", "__eq__", "__hash__",
                "__lt__", "__le__", "__gt__", "__ge__", "__add__", "__sub__",
                "__mul__", "__getitem__", "__setitem__", "__len__", "__iter__",
                "__next__", "__call__", "__contains__",
            ):
                feats.add("dunder_methods")
        if isinstance(node, ast.AnnAssign) and node.value is not None:
            has_typed_assign = True
        if isinstance(node, ast.Global):
            feats.add("global_state")
        if isinstance(node, ast.Nonlocal):
            feats.add("closures")

    if has_typed_arg or has_typed_return or has_typed_assign:
        feats.add("type_hints")

    return feats


def first_line(doc: str) -> str:
    if not doc:
        return ""
    return doc.strip().splitlines()[0].strip()


# Old: code excerpts were capped at 70 lines.  We now show the full body
# of every function and class so nothing the codebase actually contains
# gets truncated for the book.
MAX_EXCERPT_LINES = None


def excerpt_for(src: str, node: ast.AST) -> str:
    """Return the full source text of a node — no truncation.

    The book intentionally shows every line of every function and
    class so the reader can copy-paste the real implementation, not
    a redacted summary.
    """
    try:
        text = ast.get_source_segment(src, node) or ""
    except Exception:
        return ""
    if MAX_EXCERPT_LINES is not None:
        lines = text.splitlines()
        if len(lines) > MAX_EXCERPT_LINES:
            kept = lines[:MAX_EXCERPT_LINES]
            kept.append(
                f"# ... ({len(lines) - MAX_EXCERPT_LINES} more lines, "
                "truncated for the book)"
            )
            text = "\n".join(kept)
    return text


def extract_module(path: Path) -> dict:
    src = path.read_text(encoding="utf-8", errors="replace")
    info = {
        "path": path,
        "src": src,
        "loc": src.count("\n") + 1,
        "doc": "",
        "imports": [],
        "import_modules": [],
        "constants": [],
        "classes": [],
        "functions": [],
        "features": set(),
        "parse_error": None,
    }
    try:
        tree = ast.parse(src)
    except SyntaxError as e:
        info["parse_error"] = str(e)
        return info

    info["doc"] = (ast.get_docstring(tree) or "").strip()
    info["features"] = detect_features(tree)
    info["import_records"] = build_import_records(tree)

    for node in tree.body:
        if isinstance(node, ast.Import):
            for n in node.names:
                info["imports"].append(
                    f"import {n.name}" + (f" as {n.asname}" if n.asname else "")
                )
                info["import_modules"].append(n.name.split(".")[0])
        elif isinstance(node, ast.ImportFrom):
            mod = ("." * node.level) + (node.module or "")
            names = ", ".join(
                n.name + (f" as {n.asname}" if n.asname else "") for n in node.names
            )
            info["imports"].append(f"from {mod} import {names}")
            if node.module:
                info["import_modules"].append(node.module.split(".")[0])
        elif isinstance(node, ast.Assign):
            for tgt in node.targets:
                if isinstance(tgt, ast.Name) and tgt.id.isupper():
                    try:
                        val = ast.unparse(node.value)
                    except Exception:
                        val = "..."
                    if len(val) > 140:
                        val = val[:137] + "..."
                    info["constants"].append(f"{tgt.id} = {val}")
        elif isinstance(node, ast.AnnAssign):
            if isinstance(node.target, ast.Name) and node.target.id.isupper():
                try:
                    ann = ast.unparse(node.annotation)
                except Exception:
                    ann = "?"
                val = ""
                if node.value is not None:
                    try:
                        val = " = " + ast.unparse(node.value)
                    except Exception:
                        val = " = ..."
                if len(val) > 140:
                    val = val[:137] + "..."
                info["constants"].append(f"{node.target.id}: {ann}{val}")
        elif isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            info["functions"].append({
                "name": node.name,
                "signature": fmt_signature(node),
                "doc": (ast.get_docstring(node) or "").strip(),
                "is_async": isinstance(node, ast.AsyncFunctionDef),
                "lineno": node.lineno,
                "rationales": analyze_function(node),
                "steps": describe_steps(node),
                "excerpt": excerpt_for(src, node),
            })
        elif isinstance(node, ast.ClassDef):
            bases = []
            for b in node.bases:
                try:
                    bases.append(ast.unparse(b))
                except Exception:
                    bases.append("?")
            methods, attrs = [], []
            for sub in node.body:
                if isinstance(sub, (ast.FunctionDef, ast.AsyncFunctionDef)):
                    methods.append({
                        "name": sub.name,
                        "signature": fmt_signature(sub),
                        "doc": (ast.get_docstring(sub) or "").strip(),
                        "is_async": isinstance(sub, ast.AsyncFunctionDef),
                        "lineno": sub.lineno,
                        "rationales": analyze_function(sub),
                        "steps": describe_steps(sub),
                        "excerpt": excerpt_for(src, sub),
                    })
                elif isinstance(sub, ast.Assign):
                    for tgt in sub.targets:
                        if isinstance(tgt, ast.Name):
                            try:
                                val = ast.unparse(sub.value)
                            except Exception:
                                val = "..."
                            if len(val) > 100:
                                val = val[:97] + "..."
                            attrs.append(f"{tgt.id} = {val}")
                elif isinstance(sub, ast.AnnAssign) and isinstance(sub.target, ast.Name):
                    try:
                        ann = ast.unparse(sub.annotation)
                    except Exception:
                        ann = "?"
                    val = ""
                    if sub.value is not None:
                        try:
                            val = " = " + ast.unparse(sub.value)
                        except Exception:
                            val = " = ..."
                    attrs.append(f"{sub.target.id}: {ann}{val}")
            decos = []
            for d in node.decorator_list:
                try:
                    decos.append("@" + ast.unparse(d))
                except Exception:
                    pass
            # Show the entire class body — the user explicitly wanted
            # nothing cut.  Methods are still rendered separately below.
            cls_excerpt = excerpt_for(src, node)
            info["classes"].append({
                "name": node.name,
                "bases": bases,
                "decorators": decos,
                "doc": (ast.get_docstring(node) or "").strip(),
                "methods": methods,
                "attrs": attrs,
                "lineno": node.lineno,
                "excerpt": cls_excerpt,
            })

    return info


# ---------------------------------------------------------------------------
# 2b.  Frontend extraction — HTML templates, CSS, and embedded JS
# ---------------------------------------------------------------------------
#
# The Python AST scanner above gives us the server side.  This block adds a
# parallel scanner for the user-facing layer: every .html template under
# dashboard/templates and the css under dashboard/static.  We use regex
# rather than a real HTML parser because Jinja makes templates technically
# malformed HTML (mustache syntax inside attributes), and because we only
# need surface-level signals: which template extends which, what blocks
# it defines, what routes it links to, what JS libraries it pulls in.

TEMPLATE_HINTS = {
    "index.html": (
        "The home/landing page after login. The largest template in the "
        "project — embeds the live dashboard widgets, charts, and most of "
        "the client-facing data tables. If you only read one template, "
        "read this one: it is where the 'shape' of the dashboard lives."
    ),
    "login.html": (
        "The sign-in screen. Reads email + password, posts to the login "
        "route, then redirects based on the user's role (admin / trader / "
        "client). Also renders password-reset prompts when applicable."
    ),
    "change_password.html": (
        "Forced password change after first login or admin reset. "
        "POSTs the new password and runs strength validation client-side "
        "before the server enforces it again."
    ),
    "admin_dashboard.html": (
        "Top-level admin landing page. Shows system-wide KPIs, the user "
        "hierarchy, and shortcuts to management tools. Lighter than "
        "super_admin.html — it is for day-to-day operators."
    ),
    "super_admin.html": (
        "Super-admin console. Adds operations (user CRUD, system-level "
        "toggles, deeper audit views) that ordinary admins cannot run. "
        "This is the second-largest template in the project."
    ),
    "hierarchy.html": (
        "The visual Admin &rarr; Trader &rarr; Client tree, with edit "
        "handles to move users between branches. Edits POST back to the "
        "hierarchy endpoints in dashboard/app.py."
    ),
    "client_management.html": (
        "Per-trader client roster and CRUD operations: add a client, "
        "deactivate, transfer, edit the metadata that follows them around."
    ),
    "client_performance.html": (
        "Performance breakdown for a single client: accounts, payouts, "
        "hedging results, fees. Charts rendered client-side from JSON "
        "fed by the backend."
    ),
    "trader_dashboard.html": (
        "Trader's own dashboard view — their clients, their accounts, "
        "their performance summary. The trader-facing equivalent of "
        "admin_dashboard.html."
    ),
    "trader_performance.html": (
        "Per-trader performance numbers, comparable to "
        "client_performance but rolled up to the trader aggregation."
    ),
    "financial_overview.html": (
        "Cross-organisation money view: revenue, fees, payouts, P&amp;L. "
        "The financial source of truth for the dashboard. Matches the "
        "calculations done in dashboard/financial_overview.py."
    ),
    "payout_history.html": (
        "Auditable list of past payouts, filterable by client, account, "
        "and date. Drives the data shown alongside payouts.csv-style "
        "exports."
    ),
    "quality_dashboard.html": (
        "Data-quality dashboard. Surfaces ingestion health, mismatches "
        "between sources, missing fields, and sync gaps so the team "
        "spots problems before clients do."
    ),
    "maintenance.html": (
        "Maintenance-mode shield page. Served when the app is "
        "intentionally taken offline (during deploys, schema changes, "
        "or incident response)."
    ),
    "500.html": (
        "Error page rendered for unhandled server errors. Deliberately "
        "minimal: when the rest of the app is on fire, this template "
        "must not require anything of it."
    ),
    "temp_test.html": (
        "A scratch template (5 lines) — a debugging stub left over from "
        "development; not user-facing."
    ),
}


# Regex patterns we search for in HTML/Jinja files.  Built once at import
# time because we run them across many files.
_RE_EXTENDS = re.compile(r"{%-?\s*extends\s+['\"]([^'\"]+)['\"]\s*-?%}")
_RE_BLOCK = re.compile(r"{%-?\s*block\s+(\w+)\s*-?%}")
_RE_INCLUDE = re.compile(r"{%-?\s*include\s+['\"]([^'\"]+)['\"]")
_RE_URL_FOR = re.compile(r"url_for\(\s*['\"]([^'\"]+)['\"]")
_RE_FORM = re.compile(
    r"<form[^>]*?action\s*=\s*['\"]([^'\"]*)['\"][^>]*?method\s*=\s*['\"]?(\w+)",
    re.IGNORECASE | re.DOTALL,
)
_RE_FORM_NO_ACTION = re.compile(
    r"<form[^>]*?method\s*=\s*['\"]?(\w+)[^>]*?>", re.IGNORECASE,
)
_RE_SCRIPT_OPEN = re.compile(r"<script\b[^>]*>", re.IGNORECASE)
_RE_STYLE_OPEN = re.compile(r"<style\b[^>]*>", re.IGNORECASE)
_RE_EXT_SCRIPT = re.compile(
    r"<script[^>]*\bsrc\s*=\s*['\"]([^'\"]+)['\"]", re.IGNORECASE,
)
_RE_EXT_STYLE = re.compile(
    r"<link[^>]*\bhref\s*=\s*['\"]([^'\"]+\.css[^'\"]*)['\"]", re.IGNORECASE,
)
_RE_FOR_TAG = re.compile(r"{%-?\s*for\s+")
_RE_IF_TAG = re.compile(r"{%-?\s*if\s+")
_RE_INTERP = re.compile(r"{{[^}]+}}")
_RE_ENDPOINT = re.compile(r"['\"](/[\w\-/]+)['\"]")

UI_LIBRARY_HINTS = [
    ("Bootstrap", r"bootstrap(?:\.min)?\.css|getbootstrap"),
    ("Tailwind", r"tailwind"),
    ("Chart.js", r"chart\.(?:js|min\.js)|new\s+Chart\("),
    ("Plotly", r"plotly"),
    ("DataTables", r"datatables|\.DataTable\("),
    ("jQuery", r"jquery(?:\-\d|\.min\.js|\.js)"),
    ("HTMX", r"\bhtmx\b|hx-(?:get|post|swap|target|trigger)"),
    ("Alpine.js", r"alpinejs|x-data\b"),
    ("Font Awesome", r"font-?awesome|fa-\w+"),
    ("Google Fonts", r"fonts\.googleapis\.com"),
]

AJAX_HINTS = [
    ("fetch()", r"\bfetch\s*\("),
    ("XMLHttpRequest", r"\bXMLHttpRequest\b"),
    ("axios", r"\baxios\."),
    ("jQuery $.ajax", r"\$\.ajax\("),
    ("HTMX hx-* attrs", r"\bhx-(?:get|post|put|delete)\s*="),
]


def extract_template(path: Path) -> dict:
    """Parse a single .html template and surface the signals worth
    putting in the book."""
    src = path.read_text(encoding="utf-8", errors="replace")
    loc = src.count("\n") + 1

    extends_m = _RE_EXTENDS.search(src)
    forms_with_action = _RE_FORM.findall(src)
    forms_method_only = []
    if not forms_with_action:
        for m in _RE_FORM_NO_ACTION.finditer(src):
            forms_method_only.append(("(self)", m.group(1)))

    info: dict = {
        "path": path,
        "loc": loc,
        "bytes": len(src.encode("utf-8")),
        "extends": extends_m.group(1) if extends_m else None,
        "blocks": _RE_BLOCK.findall(src),
        "includes": _RE_INCLUDE.findall(src),
        "url_for": sorted(set(_RE_URL_FOR.findall(src))),
        "forms": forms_with_action or forms_method_only,
        "external_scripts": _RE_EXT_SCRIPT.findall(src),
        "external_styles": _RE_EXT_STYLE.findall(src),
        "n_for": len(_RE_FOR_TAG.findall(src)),
        "n_if": len(_RE_IF_TAG.findall(src)),
        "n_interp": len(_RE_INTERP.findall(src)),
        "n_scripts": len(_RE_SCRIPT_OPEN.findall(src)),
        "n_styles": len(_RE_STYLE_OPEN.findall(src)),
        "uses_csrf": "csrf_token" in src,
        "uses_current_user": "current_user" in src,
        "uses_flashes": "get_flashed_messages" in src,
    }

    libs: list[str] = []
    for name, pat in UI_LIBRARY_HINTS:
        if re.search(pat, src, re.IGNORECASE):
            libs.append(name)
    info["ui_libs"] = libs

    ajax: list[str] = []
    for name, pat in AJAX_HINTS:
        if re.search(pat, src):
            ajax.append(name)
    info["ajax"] = ajax

    # Excerpt: the first ~30 non-trivial lines.  Skips the doctype/charset
    # boilerplate so the reader sees the *real* template start.
    lines = src.split("\n")
    excerpt: list[str] = []
    started = False
    for ln in lines:
        if not started:
            stripped = ln.strip()
            if not stripped:
                continue
            if stripped.startswith(("<!doctype", "<!DOCTYPE", "<html", "<head")):
                excerpt.append(ln)
                started = True
                continue
            started = True
            excerpt.append(ln)
        else:
            excerpt.append(ln)
        if len(excerpt) >= 30:
            break
    info["excerpt"] = "\n".join(excerpt)
    return info


def collect_templates() -> list[Path]:
    """All real Flask templates (skips deployment_package and the
    trivial scratch stub)."""
    out: list[Path] = []
    tdir = REPO_ROOT / "dashboard" / "templates"
    if not tdir.exists():
        return out
    for p in sorted(tdir.glob("*.html")):
        if p.name == "temp_test.html":
            continue
        out.append(p)
    return out


def collect_static_assets() -> dict:
    """Collect the CSS/JS/static files alongside templates."""
    info: dict = {
        "css_files": [],
        "static_html": [],
    }
    css_dir = REPO_ROOT / "dashboard" / "static" / "css"
    if css_dir.exists():
        for p in sorted(css_dir.glob("*.css")):
            try:
                src = p.read_text(encoding="utf-8", errors="replace")
                info["css_files"].append({
                    "path": p,
                    "loc": src.count("\n") + 1,
                    "bytes": len(src.encode("utf-8")),
                    "n_rules": src.count("{"),
                    "n_media": len(re.findall(r"@media\b", src)),
                    "n_keyframes": len(re.findall(r"@keyframes\b", src)),
                    "n_vars": len(re.findall(r"--[\w-]+\s*:", src)),
                })
            except Exception:
                pass
    static_dir = REPO_ROOT / "dashboard" / "static"
    if static_dir.exists():
        for p in sorted(static_dir.glob("*.html")):
            info["static_html"].append(p)
    return info


# ---------------------------------------------------------------------------
# 3.  Educational content — Python concepts primer + per-feature explainers
# ---------------------------------------------------------------------------


CONCEPTS_PRIMER = [
    {
        "key": "modules",
        "title": "Modules and packages",
        "body": (
            "Every <b>.py</b> file in Python is a <i>module</i>. A folder with an "
            "<b>__init__.py</b> file is a <i>package</i>. When you write "
            "<code>from trader_companion import mt5_trading</code>, Python finds the "
            "module file, executes it from top to bottom, and exposes the names "
            "defined inside (functions, classes, constants) under that module. "
            "Imports run only the first time — subsequent imports get the cached "
            "module object. This is why placing side-effect-heavy code at module "
            "scope is risky: it runs whenever the module is imported anywhere "
            "in the program."
        ),
    },
    {
        "key": "classes",
        "title": "Classes and objects",
        "body": (
            "A class is a blueprint for objects. Calling the class — for example "
            "<code>Trade(symbol='EURUSD', volume=0.1)</code> — runs the special "
            "<b>__init__</b> method to construct an instance. Methods defined "
            "inside the class take <code>self</code> as their first parameter; "
            "Python passes the instance in automatically when you call "
            "<code>trade.close()</code>. Attributes set on <code>self</code> are "
            "per-instance; attributes set at class scope are shared across "
            "instances unless overridden."
        ),
    },
    {
        "key": "inheritance",
        "title": "Inheritance",
        "body": (
            "A class can inherit from one (or many) base classes by listing them "
            "in parentheses: <code>class Topstep(PropFirm):</code>. The subclass "
            "gets every method and attribute from its parent for free, but can "
            "override any of them. <code>super().method()</code> calls the "
            "parent's version — useful when you want to extend behaviour rather "
            "than replace it. Inheritance is one form of code reuse; "
            "composition (holding another object as an attribute) is often "
            "simpler and more flexible."
        ),
    },
    {
        "key": "decorators",
        "title": "Decorators",
        "body": (
            "A decorator is a function that wraps another function (or class) "
            "to add behaviour. Writing <code>@app.route('/login')</code> above "
            "a function is shorthand for <code>login = app.route('/login')(login)</code>. "
            "Decorators are how Flask attaches URL handlers, how "
            "<code>@property</code> turns a method into an attribute lookup, "
            "and how <code>@staticmethod</code> tells Python that a method "
            "doesn't need <code>self</code>. Decorators stack: the one closest "
            "to the function runs first."
        ),
    },
    {
        "key": "type_hints",
        "title": "Type hints",
        "body": (
            "Python is dynamically typed at runtime, but you can annotate "
            "parameters and returns: <code>def fetch(account: int) -> Trade:</code>. "
            "These annotations are not enforced — they exist for static "
            "checkers like mypy/pyright, IDE auto-complete, and human "
            "readers. The <b>typing</b> module supplies generics like "
            "<code>list[int]</code>, <code>Optional[str]</code>, and "
            "<code>dict[str, Any]</code>. From Python 3.10 onwards you can "
            "write <code>int | None</code> in place of <code>Optional[int]</code>."
        ),
    },
    {
        "key": "async",
        "title": "Async / await",
        "body": (
            "<b>async def</b> declares a coroutine — a function that returns "
            "an awaitable rather than a value. Inside it, <b>await</b> hands "
            "control back to the event loop while it waits for I/O. This lets "
            "a single thread juggle many slow operations (HTTP requests, "
            "websocket reads) concurrently without blocking. You launch "
            "coroutines with <code>asyncio.run(main())</code> or schedule "
            "them as tasks with <code>asyncio.create_task(coro)</code>."
        ),
    },
    {
        "key": "generators",
        "title": "Generators and yield",
        "body": (
            "A function that uses <b>yield</b> instead of <b>return</b> "
            "becomes a generator: each call returns an iterator that produces "
            "values one at a time, on demand. This is how Python streams data "
            "without holding it all in memory. <code>for row in read_csv(path)</code> "
            "can iterate a million-row file lazily. <code>yield from</code> "
            "delegates to another iterator; combined with coroutines, "
            "generators were the foundation for async/await."
        ),
    },
    {
        "key": "context_managers",
        "title": "Context managers (with-statements)",
        "body": (
            "<code>with open('file') as f:</code> guarantees that "
            "<code>f.close()</code> runs whether the block succeeds or "
            "raises. The object's <b>__enter__</b> runs at the start, "
            "<b>__exit__</b> at the end. Context managers express the "
            "acquire/release pattern: locks, database connections, "
            "transactions, temp files, MetaTrader-5 sessions. The "
            "<code>contextlib.contextmanager</code> decorator turns a "
            "generator into a context manager when you don't want to write "
            "the dunder methods by hand."
        ),
    },
    {
        "key": "dataclasses",
        "title": "Dataclasses",
        "body": (
            "A <code>@dataclass</code> auto-generates <b>__init__</b>, "
            "<b>__repr__</b>, and <b>__eq__</b> from the class's annotated "
            "fields. It removes the boilerplate from \"plain data\" objects. "
            "Use <code>field(default_factory=list)</code> for mutable defaults "
            "(never write <code>= []</code> at class scope — it leaks state "
            "across instances). <code>frozen=True</code> makes instances "
            "hashable and immutable."
        ),
    },
    {
        "key": "exceptions",
        "title": "Exceptions",
        "body": (
            "Errors in Python travel up the call stack until something "
            "catches them. <code>try/except</code> catches; "
            "<code>raise</code> throws; <code>finally</code> runs cleanup "
            "regardless. Catch the narrowest exception you can — "
            "<code>except Exception</code> as the only handler will swallow "
            "<code>KeyboardInterrupt</code> on older code paths and hide "
            "real bugs. Define your own exception types by subclassing "
            "<code>Exception</code> when callers need to distinguish "
            "failure modes."
        ),
    },
    {
        "key": "comprehensions",
        "title": "Comprehensions",
        "body": (
            "<code>[x*2 for x in xs if x > 0]</code> builds a list in one "
            "expression. There are list, set, dict, and generator versions. "
            "Generator comprehensions use parentheses: "
            "<code>sum(x*2 for x in xs)</code> avoids materialising the "
            "intermediate list. Comprehensions are usually clearer than "
            "<code>map</code>/<code>filter</code> and faster than the "
            "equivalent for-loop because the list is sized once."
        ),
    },
    {
        "key": "properties",
        "title": "Properties",
        "body": (
            "<code>@property</code> turns a method into an attribute lookup. "
            "<code>account.equity</code> can run a calculation each time it "
            "is accessed without exposing the call syntax. A matching "
            "<code>@equity.setter</code> lets you intercept assignment. "
            "Properties are how you migrate a public attribute to a "
            "computed value without breaking callers."
        ),
    },
    {
        "key": "fstrings",
        "title": "f-strings",
        "body": (
            "<code>f\"Account {a.id} balance ${a.balance:,.2f}\"</code> is "
            "Python's modern interpolation syntax. The format spec after "
            "the colon (<code>,.2f</code>, <code>%</code>, <code>:&lt;20</code>) "
            "controls width, precision, and alignment. f-strings are "
            "compiled into the bytecode at parse time, so they are also "
            "the fastest formatting option."
        ),
    },
    {
        "key": "lambdas",
        "title": "Lambdas",
        "body": (
            "A <b>lambda</b> is a single-expression anonymous function. "
            "<code>sorted(trades, key=lambda t: t.profit)</code> avoids "
            "naming a one-line helper. Anything more than a single "
            "expression should be a regular <code>def</code> — lambdas "
            "lose statements, type hints, and a useful traceback name."
        ),
    },
    {
        "key": "dunder_methods",
        "title": "Dunder methods",
        "body": (
            "Methods with double-underscore names (<b>__init__</b>, "
            "<b>__repr__</b>, <b>__eq__</b>, <b>__len__</b>) hook into "
            "Python's syntax. Defining <b>__len__</b> makes "
            "<code>len(obj)</code> work; <b>__iter__</b> makes it usable "
            "in <code>for</code>; <b>__getitem__</b> enables "
            "<code>obj[key]</code>. They are how user-defined classes "
            "behave like built-in types."
        ),
    },
    {
        "key": "classmethod_staticmethod",
        "title": "@classmethod and @staticmethod",
        "body": (
            "<code>@classmethod</code> receives the class itself as its "
            "first argument (<code>cls</code> by convention). It is the "
            "standard way to define alternate constructors: "
            "<code>Trade.from_mt5_order(...)</code>. "
            "<code>@staticmethod</code> takes neither <code>self</code> "
            "nor <code>cls</code> — use it when a function logically "
            "belongs to the class's namespace but doesn't need access to "
            "any state."
        ),
    },
    {
        "key": "global_state",
        "title": "Module-level state",
        "body": (
            "Variables assigned at module top-level are global to that "
            "module. They are convenient for caches and singletons, but "
            "they can make testing harder because every import shares the "
            "same instance. Prefer passing values explicitly; reach for "
            "module-level state only when there is genuinely one of "
            "something (a database engine, a logger)."
        ),
    },
]


CONCEPT_TITLES = {c["key"]: c["title"] for c in CONCEPTS_PRIMER}
CONCEPT_TITLES.update({
    "flask_routes": "Flask routes",
    "abstract_classes": "Abstract base classes",
    "custom_exceptions": "Custom exception types",
    "enums": "Enums",
    "typed_dict": "TypedDict",
    "named_tuple": "NamedTuple",
    "pydantic": "Pydantic models",
    "orm_model": "ORM models",
    "match_case": "match / case",
    "walrus": "Walrus operator (:=)",
    "closures": "Closures",
})


# Plain-English descriptions for known directories.
DIR_DESCRIPTIONS = {
    "(root)": (
        "Top-level scripts that wire the application together: deployment "
        "preparation, the WSGI entry point Gunicorn loads in production, "
        "and helper utilities for managing users and database migrations."
    ),
    "trader_companion": (
        "The desktop trader-side companion. This is the largest module of "
        "the codebase. It connects to MetaTrader 5 over the official "
        "Python API, reads order history, hedges open positions across "
        "linked accounts, scrapes prop-firm dashboards (Topstep, "
        "FundedNext, Tradovate, TradeOpss) for funded-account state, and "
        "runs a Tkinter GUI that the trader interacts with."
    ),
    "dashboard": (
        "The web dashboard served via Flask. It exposes admin and trader "
        "views, manages accounts and payouts, runs scheduled jobs against "
        "Google Sheets and the database, and surfaces financial "
        "performance, payout history, and quality metrics."
    ),
    "connectors": (
        "Low-level wrappers around the MetaTrader 5 terminal: connection "
        "lifecycle, account login, and a thin automation layer."
    ),
    "config": (
        "Application settings. Keys, environment toggles, the firm "
        "hierarchy data, and production overrides live here."
    ),
    "utils": (
        "Cross-cutting helper utilities used by both the desktop "
        "companion and the dashboard."
    ),
    "alembic": (
        "Database migration scaffolding. Each version file under "
        "alembic/versions is a forward + rollback step for the "
        "PostgreSQL schema."
    ),
}


# Per-file synopsis hints. Keys are filenames, values are extra prose.
FILE_HINTS = {
    "wsgi.py": (
        "The WSGI entry point. Gunicorn imports the application object "
        "from this module in production. Keep it small — its only job is "
        "to construct the app and expose it under a stable name."
    ),
    "gunicorn.conf.py": (
        "Gunicorn configuration. Worker counts, bind address, timeouts, "
        "and logging are read from variables at module scope."
    ),
    "build.py": (
        "PyInstaller-driven build script. Packages the desktop trader "
        "companion into a Windows executable using one of the .spec "
        "files in the repo root."
    ),
    "manage_users.py": (
        "CLI for creating, deleting, and resetting password for users in "
        "the dashboard's authentication table. Run from the deployment "
        "shell when onboarding admins."
    ),
    "migrations.py": "Glue around alembic for invoking migrations from Python.",
    "prepare_deployment.py": (
        "Bundles the dashboard subset for deployment to the production "
        "host (PythonAnywhere). Copies the curated file list into "
        "deployment_package/ and zips it."
    ),
    "trader_app.py": (
        "The Tkinter main window. Wires together the MT5 connection, "
        "the prop-firm scrapers, the trade-limit manager, and the hedge "
        "protector under a tabbed UI. The largest single file in the "
        "codebase."
    ),
    "mt5_trading.py": (
        "All MetaTrader 5 trading helpers: order submission, position "
        "lookup, fill reconciliation. Wraps the official MetaTrader5 "
        "Python package."
    ),
    "hedge_protector.py": (
        "The hedging engine. Watches a primary account for net exposure "
        "and opens offsetting positions on a hedge account so that "
        "drawdown on the funded leg is bounded."
    ),
    "prop_firm_manager.py": (
        "Coordinates the per-firm scraper instances, normalises their "
        "outputs, and pushes account state to the dashboard."
    ),
    "prop_firm_scrapers.py": (
        "Browser-automation scrapers (Selenium / Chrome DevTools "
        "Protocol) that pull account state out of prop-firm dashboards "
        "that have no official API."
    ),
    "fundednext.py": "FundedNext-specific scraper and account adapter.",
    "topstepx.py": "TopstepX-specific scraper and account adapter.",
    "tradovate.py": "Tradovate-specific scraper and account adapter.",
    "trade_limit_manager.py": (
        "Enforces per-account daily loss and position-size limits. The "
        "guardrail that prevents one bad day from killing a funded "
        "account."
    ),
    "broker_selection.py": (
        "Model + helpers for choosing which broker terminal to connect "
        "to when multiple MT5 installations are present."
    ),
    "mt5_comment_parser.py": (
        "Parses the structured comment field on MT5 orders so that "
        "trades can be linked back to the strategy that placed them."
    ),
    "mt5_dashboard_sync.py": (
        "Periodically pushes the local MT5 deal history to the "
        "dashboard's database."
    ),
    "push_data.py": "Outbound HTTP client for the dashboard's ingestion API.",
    "app.py": (
        "The Flask application factory. Registers blueprints, sets up "
        "session config, attaches scheduled jobs, and exposes the "
        "request-time hooks (login required, role checks)."
    ),
    "models.py": (
        "SQLAlchemy ORM models. Each class corresponds to a table; "
        "fields use Column declarations; relationships are defined via "
        "relationship() and back-populated on the other side."
    ),
    "database.py": (
        "Database engine and session factory. The single source of "
        "connections used across the app."
    ),
    "db.py": (
        "Lower-level convenience wrappers around the SQLAlchemy session "
        "for places that don't want the ORM overhead."
    ),
    "scheduler.py": (
        "APScheduler setup. Cron-style jobs that resync from Google "
        "Sheets, recompute statistics, and send notifications."
    ),
    "phase_manager.py": (
        "State machine that tracks each account's evaluation phase: "
        "challenge, verification, funded. Drives payout eligibility."
    ),
    "watermark_service.py": (
        "Tracks high-water marks for accounts so that payout "
        "calculations only credit profit above the previous peak."
    ),
    "financial_overview.py": (
        "Aggregates deposits, withdrawals, fees, and payouts into the "
        "Financial Overview tab the admin dashboard renders."
    ),
    "email_service.py": (
        "SMTP-backed transactional email helpers — password resets, "
        "payout notifications, alert digests."
    ),
    "manage_api_keys.py": (
        "Creates and revokes API keys used by the desktop companion "
        "to authenticate to the dashboard's ingestion endpoints."
    ),
    "notes_service.py": (
        "Per-account notes (free-text annotations admins leave on "
        "trader accounts)."
    ),
    "api_client.py": (
        "Outbound HTTP client used by the dashboard to talk to "
        "external APIs (Google Sheets, prop-firm endpoints)."
    ),
    "calc_like_sheet.py": (
        "Replicates the formulas in the source-of-truth Google Sheet "
        "so the dashboard's numbers match what the trader sees in "
        "their sheet."
    ),
    "sheet_helper.py": "Thin wrapper over the Google Sheets API.",
    "trade_matcher.py": (
        "Reconciles MT5 deal history against the sheet's trade list to "
        "detect missing or duplicated entries."
    ),
    "mt5_connector.py": (
        "Manages the lifecycle of the MetaTrader 5 connection: "
        "initialize, login, shutdown, and reconnection on failure."
    ),
    "mt5_automator.py": (
        "Higher-level helper for issuing MT5 commands without callers "
        "having to handle the request/result tuples directly."
    ),
    "settings.py": (
        "Centralised configuration. Reads from environment variables "
        "with sensible local-development defaults."
    ),
    "production.py": "Production-only overrides for settings.py.",
    "hierarchy.py": (
        "Loads and validates the firm hierarchy (admin / manager / "
        "trader) tree out of hierarchy.json."
    ),
    "data_processor.py": (
        "Generic dataframe helpers — date normalisation, currency "
        "parsing, signed-number coercion."
    ),
    "config.py": "Module-scoped settings for the trader companion.",
    "trading_helpers.py": "Pure helpers used by the signal modules.",
    "rsi.py": (
        "Relative Strength Index. The most-developed signal in the "
        "tree — illustrates how the rest of the signals are organised."
    ),
    "env.py": "Alembic environment hook. Configures the migration runner.",
}


SIGNAL_FOLDER_NOTE = (
    "Each file in <b>trader_companion/signals/</b> implements a single "
    "technical indicator. They follow the same shape: a function that "
    "takes a pandas DataFrame of OHLC bars and returns a Series of the "
    "indicator's values. Many are placeholders today — the signals that "
    "are wired into strategies are <b>rsi</b>, <b>ema</b>, <b>sma</b>, "
    "<b>macd</b>, <b>bb</b>, <b>atr</b>, and <b>supertrend</b>."
)


# ---------------------------------------------------------------------------
# 3a.  Build phases — order modules by the dependency-correct sequence a
#      reader following along should construct the project in.
# ---------------------------------------------------------------------------


BUILD_PHASES: list[dict] = [
    {
        "title": "Phase 1 — Foundations: configuration and shared helpers",
        "intro": (
            "Every project starts with the boring-but-essential plumbing: "
            "a place for settings (the values that change between dev and "
            "production), and a small kit of helpers shared by everything "
            "else. We build these first because every later phase imports "
            "them. If you have not yet created a <code>config/</code> and "
            "<code>utils/</code> folder under your project root, do that "
            "now — Python only treats a folder as a package when it "
            "contains an <code>__init__.py</code> file, even an empty one."
        ),
        "files": [
            "config/settings.py",
            "config/production.py",
            "config/hierarchy.py",
            "utils/__init__.py",
            "utils/data_processor.py",
        ],
    },
    {
        "title": "Phase 2 — Persistence: the database layer",
        "intro": (
            "Trading data has to live somewhere — accounts, payouts, "
            "watermarks, deals, notes. We use PostgreSQL in production "
            "and SQLite for development, talking to both through "
            "SQLAlchemy. Alembic owns the schema: each version file "
            "describes a forward step (\"add this column\") and a "
            "rollback step (\"drop it\"). In this phase we wire the "
            "engine, declare the ORM models that mirror the tables, and "
            "scaffold the first two Alembic revisions."
        ),
        "files": [
            "alembic/env.py",
            "alembic/versions/44e368d8bfce_initial_schema.py",
            "alembic/versions/5b29b54b57fa_add_firm_billing_column.py",
            "dashboard/database.py",
            "dashboard/db.py",
            "dashboard/models.py",
        ],
    },
    {
        "title": "Phase 3 — Talking to MetaTrader 5",
        "intro": (
            "The MT5 terminal exposes a Python API through the "
            "<code>MetaTrader5</code> package. Before we can place a "
            "trade or read history, we need a thin wrapper that opens "
            "and closes the connection cleanly. That wrapper lives in "
            "<code>connectors/</code>; everything in later phases that "
            "talks to MT5 goes through it."
        ),
        "files": [
            "connectors/mt5_connector.py",
            "connectors/mt5_automator.py",
        ],
    },
    {
        "title": "Phase 4 — Indicators and strategies",
        "intro": (
            "A strategy is a recipe that decides when to buy or sell. "
            "Most strategies are built out of <i>technical indicators</i> "
            "— RSI, moving averages, Bollinger Bands. Each indicator is "
            "a tiny pure function: it takes a pandas DataFrame of OHLC "
            "bars and returns a Series of values. We build the helper "
            "module first, then a single indicator template, then the "
            "rest, and finally the strategy that combines them."
        ),
        "files": [
            "trader_companion/utils/__init__.py",
            "trader_companion/utils/config.py",
            "trader_companion/utils/trading_helpers.py",
            "trader_companion/signals/__init__.py",
            "trader_companion/signals/sma.py",
            "trader_companion/signals/ema.py",
            "trader_companion/signals/rsi.py",
            "trader_companion/signals/macd.py",
            "trader_companion/signals/bb.py",
            "trader_companion/signals/atr.py",
            "trader_companion/signals/adx.py",
            "trader_companion/signals/dmi.py",
            "trader_companion/signals/cci.py",
            "trader_companion/signals/momentum.py",
            "trader_companion/signals/roc.py",
            "trader_companion/signals/obv.py",
            "trader_companion/signals/mfi.py",
            "trader_companion/signals/stochastic.py",
            "trader_companion/signals/supertrend.py",
            "trader_companion/signals/sar.py",
            "trader_companion/signals/tsi.py",
            "trader_companion/signals/wr.py",
            "trader_companion/signals/cmo.py",
            "trader_companion/signals/coppock_curve.py",
            "trader_companion/signals/donchian_channel.py",
            "trader_companion/signals/elder_ray.py",
            "trader_companion/signals/fractal.py",
            "trader_companion/signals/gator_oscillator.py",
            "trader_companion/signals/keltner_channel.py",
            "trader_companion/signals/price_channel.py",
            "trader_companion/signals/ultimate_oscillator.py",
            "trader_companion/signals/vortex.py",
            "trader_companion/strategies/__init__.py",
            "trader_companion/strategies/rsi_overbought_oversold.py",
        ],
    },
    {
        "title": "Phase 5 — The trading engine",
        "intro": (
            "Now we wire the signals and the MT5 connector together. "
            "<code>mt5_trading.py</code> sends orders and reads "
            "positions; <code>mt5_comment_parser.py</code> tags those "
            "orders with structured strategy metadata; "
            "<code>trade_limit_manager.py</code> enforces the daily "
            "loss/position-size guardrails; and "
            "<code>hedge_protector.py</code> opens offsetting "
            "positions on a hedge account so that drawdown on the "
            "funded leg is bounded. This is the heart of the system."
        ),
        "files": [
            "trader_companion/mt5_trading.py",
            "trader_companion/mt5_comment_parser.py",
            "trader_companion/trade_limit_manager.py",
            "trader_companion/hedge_protector.py",
        ],
    },
    {
        "title": "Phase 6 — Prop-firm dashboards",
        "intro": (
            "Funded accounts live behind prop-firm dashboards "
            "(Topstep, FundedNext, Tradovate, TradeOpss) that have no "
            "official API. We use Selenium and the Chrome DevTools "
            "Protocol to log in, read account state, and post it to "
            "our own database. We build a base scraper class first, "
            "then the firm-specific subclasses, then a manager that "
            "coordinates them."
        ),
        "files": [
            "trader_companion/prop_firm_scrapers.py",
            "trader_companion/fundednext.py",
            "trader_companion/topstepx.py",
            "trader_companion/tradovate.py",
            "trader_companion/prop_firm_manager.py",
        ],
    },
    {
        "title": "Phase 7 — Pushing data to the dashboard",
        "intro": (
            "The desktop companion runs on the trader's machine. The "
            "web dashboard runs on a server. They communicate through "
            "an HTTP ingestion API. In this phase we build the outbound "
            "HTTP client and the periodic sync that pushes MT5 deal "
            "history to the server."
        ),
        "files": [
            "trader_companion/push_data.py",
            "trader_companion/mt5_dashboard_sync.py",
        ],
    },
    {
        "title": "Phase 8 — Desktop GUI",
        "intro": (
            "Tkinter ships with Python — no extra install needed. We "
            "build a small broker-picker window first to learn the "
            "patterns (a window, a frame, a button, a callback), then "
            "the full trader-companion app that ties everything in "
            "phases 3–7 together under a single tabbed interface."
        ),
        "files": [
            "trader_companion/broker_selection.py",
            "trader_companion/trader_app.py",
        ],
    },
    {
        "title": "Phase 9 — Web dashboard",
        "intro": (
            "A Flask application that admins, managers, and traders "
            "log into through a browser. We build the supporting "
            "services bottom-up — email, notes, API keys, sheet "
            "synchronisation, payout calculations — and finally the "
            "Flask app factory in <code>app.py</code> that registers "
            "the routes and starts the request lifecycle."
        ),
        "files": [
            "dashboard/email_service.py",
            "dashboard/notes_service.py",
            "dashboard/manage_api_keys.py",
            "dashboard/api_client.py",
            "dashboard/utils/sheet_helper.py",
            "dashboard/utils/trade_matcher.py",
            "dashboard/calc_like_sheet.py",
            "dashboard/phase_manager.py",
            "dashboard/watermark_service.py",
            "dashboard/financial_overview.py",
            "dashboard/scheduler.py",
            "dashboard/app.py",
        ],
    },
    {
        "title": "Phase 10 — Deployment",
        "intro": (
            "Last phase. We add the entry points the production server "
            "(Gunicorn) calls, a CLI for managing users, a wrapper "
            "around Alembic migrations, the script that bundles the "
            "dashboard for deployment to PythonAnywhere, and the "
            "PyInstaller build script that packages the desktop "
            "companion into a Windows executable."
        ),
        "files": [
            "manage_users.py",
            "migrations.py",
            "wsgi.py",
            "gunicorn.conf.py",
            "prepare_deployment.py",
            "build.py",
        ],
    },
]


PHASE_CHECKPOINTS: dict[int, str] = {
    1: "<b>Checkpoint — what works now.</b> You have a configured "
       "project skeleton. Nothing runs yet — the foundations layer is "
       "pure data and helpers — but every later phase imports from "
       "these modules. Import them in a Python REPL "
       "(<code>python -c \"from config.settings import *; print('OK')\"</code>) "
       "to confirm there are no syntax errors before moving on.",
    2: "<b>Checkpoint — what works now.</b> Your database schema "
       "exists. Run <code>alembic upgrade head</code> from the project "
       "root and the dashboard.db file should appear with all tables "
       "created. Open it with <code>sqlite3 dashboard.db .schema</code> "
       "to inspect the columns. You cannot yet write rows from "
       "application code — that comes in phase 9 — but the schema is "
       "in place.",
    3: "<b>Checkpoint — what works now.</b> You can connect to the "
       "MT5 terminal from Python. Open the terminal, log in, then in a "
       "REPL: <code>from connectors.mt5_connector import MT5Connector; "
       "MT5Connector().connect()</code>. A successful return means "
       "the rest of the trading engine has something to talk to.",
    4: "<b>Checkpoint — what works now.</b> Indicator math works in "
       "isolation. Feed any indicator function a small DataFrame of "
       "OHLC bars and inspect the output Series. The strategy in "
       "<code>strategies/rsi_overbought_oversold.py</code> can now "
       "decide buy/sell on synthetic data — but it has nothing to send "
       "the decision to yet. That is the next phase.",
    5: "<b>Checkpoint — what works now.</b> The trading engine is "
       "complete. With MT5 running and a logged-in account, "
       "<code>mt5_trading.MT5Trader().place_order(...)</code> sends "
       "real orders; <code>trade_limit_manager</code> blocks ones that "
       "would breach daily limits; <code>hedge_protector</code> can "
       "open offsetting positions on a hedge account. Test on a demo "
       "account before pointing it at anything live.",
    6: "<b>Checkpoint — what works now.</b> The scrapers can log into "
       "each prop firm and read account state. Run any of them in "
       "isolation and watch a Chrome window open, log in, and "
       "navigate to the dashboard page. The data they extract is "
       "still in-memory only — it will be pushed to the server in the "
       "next phase.",
    7: "<b>Checkpoint — what works now.</b> The desktop side now "
       "talks to the dashboard. Run <code>push_data.py</code> with "
       "test data and check the rows arrive in the database. "
       "<code>mt5_dashboard_sync</code> will keep that flow running on "
       "a schedule.",
    8: "<b>Checkpoint — what works now.</b> Run "
       "<code>python trader_companion/trader_app.py</code> and the "
       "Tkinter window opens — broker selection on first launch, then "
       "the main tabbed view that exposes everything you have built "
       "in phases 3 through 7.",
    9: "<b>Checkpoint — what works now.</b> Run the Flask app "
       "(<code>flask --app dashboard.app run</code>), open "
       "<i>http://localhost:5000</i>, and you have a working web "
       "dashboard. Log in, browse accounts, view payouts and the "
       "financial overview. The scheduler is running periodic jobs in "
       "the background.",
    10: "<b>Checkpoint — what works now.</b> The project ships. "
        "<code>gunicorn -c gunicorn.conf.py wsgi:app</code> runs the "
        "dashboard in production-mode workers. "
        "<code>python build.py</code> packages the desktop companion "
        "into a Windows .exe. <code>python prepare_deployment.py</code> "
        "bundles the dashboard for upload to PythonAnywhere. The book "
        "ends here — you have built the platform.",
}


# Internal top-level names that count as "depends on earlier work".
INTERNAL_TOPS: set[str] = {
    "config", "utils", "connectors", "alembic", "trader_companion",
    "dashboard", "signals", "strategies", "watermark_service",
    "database", "models", "prop_firm_manager", "chrome_auto_compatibility",
    "phase_manager", "email_service", "notes_service", "sheet_helper",
    "trade_matcher", "api_client", "calc_like_sheet", "manage_api_keys",
    "scheduler", "push_data", "fundednext", "topstepx", "tradovate",
    "hedge_protector", "trade_limit_manager", "broker_selection",
    "mt5_trading", "mt5_comment_parser", "mt5_dashboard_sync",
    "mt5_connector", "mt5_automator", "data_processor", "hierarchy",
    "settings", "production", "financial_overview", "prop_firm_scrapers",
    "trading_helpers",
}


def internal_deps_for(m: dict) -> list[str]:
    """Return the internal modules this file imports (deduped, in order)."""
    seen: list[str] = []
    for r in m.get("import_records") or []:
        top = r["top"]
        if top in INTERNAL_TOPS and top not in seen:
            seen.append(top)
    return seen


def order_modules_by_phase(modules: list[dict]) -> list[tuple[dict, list[dict]]]:
    """Return [(phase, [module]), ...] in BUILD_PHASES order.
    Files not in any phase are appended in a synthetic 'misc' phase."""
    by_path: dict[str, dict] = {
        m["path"].relative_to(REPO_ROOT).as_posix(): m for m in modules
    }
    out: list[tuple[dict, list[dict]]] = []
    used_paths: set[str] = set()
    for phase in BUILD_PHASES:
        files = []
        for rel in phase["files"]:
            m = by_path.get(rel)
            if m is not None:
                files.append(m)
                used_paths.add(rel)
        out.append((phase, files))
    # Catch-all: anything unaccounted for goes in a misc phase
    leftover = [m for rel, m in by_path.items() if rel not in used_paths]
    if leftover:
        out.append(({
            "title": "Appendix A — Modules not on the main build path",
            "intro": "These modules exist in the source tree but are not "
                     "part of the linear walk-through above.",
            "files": [],
        }, leftover))
    return out


# ---------------------------------------------------------------------------
# 4.  PDF rendering
# ---------------------------------------------------------------------------


def make_styles():
    """Visual styles, aligned with the 'Python: The Greatest Hits' look:
    cleaner typography, more breathing room, callouts with a left-edge
    accent bar, and code blocks in a light-tinted box."""
    base = getSampleStyleSheet()
    s = {
        "title": ParagraphStyle(
            "title", parent=base["Title"], fontSize=30, leading=36,
            alignment=1, spaceAfter=14,
            textColor=colors.HexColor("#1a365d"),
        ),
        "subtitle": ParagraphStyle(
            "subtitle", parent=base["Italic"], fontSize=14, leading=20,
            alignment=1, spaceAfter=12,
            textColor=colors.HexColor("#4a5568"),
        ),
        "tag": ParagraphStyle(
            "tag", parent=base["Normal"], fontSize=11, leading=14,
            alignment=1, spaceAfter=10,
            textColor=colors.HexColor("#1a202c"),
        ),
        "chapter": ParagraphStyle(
            "chapter", parent=base["Heading1"], fontSize=24, leading=30,
            textColor=colors.HexColor("#1a365d"),
            spaceBefore=14, spaceAfter=12,
        ),
        "h1": ParagraphStyle(
            "h1", parent=base["Heading1"], fontSize=18, leading=23,
            textColor=colors.HexColor("#1a365d"),
            spaceBefore=12, spaceAfter=8,
        ),
        "h2": ParagraphStyle(
            "h2", parent=base["Heading2"], fontSize=14, leading=18,
            textColor=colors.HexColor("#2c5282"),
            spaceBefore=12, spaceAfter=6,
        ),
        "h3": ParagraphStyle(
            "h3", parent=base["Heading3"], fontSize=12, leading=15,
            textColor=colors.HexColor("#2d3748"),
            spaceBefore=10, spaceAfter=4,
        ),
        "body": ParagraphStyle(
            "body", parent=base["Normal"], fontSize=10.5, leading=15,
            spaceAfter=8,
        ),
        "body_left": ParagraphStyle(
            "body_left", parent=base["Normal"], fontSize=10.5,
            leading=15, spaceAfter=8,
        ),
        "muted": ParagraphStyle(
            "muted", parent=base["Normal"], fontSize=9, leading=12,
            textColor=colors.HexColor("#718096"), spaceAfter=4,
        ),
        "doc": ParagraphStyle(
            "doc", parent=base["Normal"], fontSize=10, leading=14,
            textColor=colors.HexColor("#2d3748"),
            leftIndent=14, spaceAfter=5,
        ),
        "code": ParagraphStyle(
            "code", parent=base["Code"], fontSize=8.5, leading=11,
            leftIndent=12, rightIndent=4,
            spaceBefore=4, spaceAfter=8,
            textColor=colors.HexColor("#1a202c"),
            backColor=colors.HexColor("#f1f5f9"),
            borderColor=colors.HexColor("#cbd5e0"),
            borderWidth=0.4, borderPadding=8,
        ),
        "tocchap": ParagraphStyle(
            "tocchap", parent=base["Normal"], fontSize=11, leading=14,
            spaceBefore=4, spaceAfter=2,
            textColor=colors.HexColor("#1a365d"),
        ),
        "tocfile": ParagraphStyle(
            "tocfile", parent=base["Normal"], fontSize=9, leading=11,
            leftIndent=14, spaceAfter=1,
        ),
        "callout": ParagraphStyle(
            "callout", parent=base["Normal"], fontSize=10.5, leading=15,
            spaceAfter=6,
            textColor=colors.HexColor("#1a202c"),
        ),
        "callout_heading_blue": ParagraphStyle(
            "callout_heading_blue", parent=base["Normal"], fontSize=12,
            leading=15, spaceAfter=6,
            textColor=colors.HexColor("#1a365d"),
        ),
        "callout_heading_orange": ParagraphStyle(
            "callout_heading_orange", parent=base["Normal"], fontSize=12,
            leading=15, spaceAfter=6,
            textColor=colors.HexColor("#9c4221"),
        ),
    }
    return s


def render_rationales(target: list, fn: dict, styles, indent_em: int = 0) -> None:
    """Append a Why-each-concept-was-used block to `target`."""
    rationales = fn.get("rationales") or []
    if not rationales:
        return
    pad = "&nbsp;" * indent_em
    target.append(Paragraph(
        pad + "<b>Why these Python concepts were used</b>",
        styles["body_left"],
    ))
    for name, why in rationales:
        target.append(Paragraph(
            f"{pad}&bull; <b>{esc(name)}</b> — {why}",
            styles["doc"],
        ))


def render_steps(target: list, fn: dict, styles, indent_em: int = 0) -> None:
    """Append a numbered Step-by-step walkthrough to `target`."""
    steps = fn.get("steps") or []
    if not steps:
        return
    pad = "&nbsp;" * indent_em
    target.append(Paragraph(
        pad + "<b>Step by step (top-level body)</b>",
        styles["body_left"],
    ))
    for i, step in enumerate(steps, 1):
        target.append(Paragraph(
            f"{pad}<b>{i}.</b> {step}",
            styles["doc"],
        ))


def render_excerpt(target: list, item: dict, styles, indent: str = "") -> None:
    """Append a code excerpt block (the actual source) to `target`.

    Note: the `indent` parameter is intentionally ignored for the excerpt
    body itself — prefixing every line with whitespace would corrupt the
    code when a reader copy-pastes it.  Visual nesting is conveyed by
    the section heading instead.
    """
    excerpt = item.get("excerpt") or ""
    if not excerpt.strip():
        return
    target.append(Paragraph(
        f"{indent}<b>Code</b> &nbsp;<font color='#a0aec0' size='8'>"
        f"(copy-paste safe)</font>", styles["body_left"],
    ))
    target.append(Preformatted(
        wrap_code(excerpt, width=110), styles["code"],
    ))
    target.append(Spacer(1, 0.05 * inch))


# Bracket characters Python treats as allowing implicit line continuation.
_OPEN_BRACKETS = "([{"
_CLOSE_BRACKETS = ")]}"


def _safe_split_point(line: str, width: int) -> int | None:
    """Find a column at which we can split `line` without breaking the
    Python (or HTML) on the page.  We prefer to break:
      * after a comma that lies inside a paren/bracket group, OR
      * after an open bracket itself,
    because Python treats those as implicit line continuations and the
    pasted code still parses.  Returns None if no safe split exists.
    """
    depth = 0
    in_str: str | None = None
    last_safe = None
    for i, ch in enumerate(line):
        if in_str:
            if ch == "\\" and i + 1 < len(line):
                continue
            if ch == in_str:
                in_str = None
            continue
        if ch in ("'", '"'):
            in_str = ch
            continue
        if ch == "#":
            break  # comments — can't safely split inside them
        if ch in _OPEN_BRACKETS:
            depth += 1
            if depth >= 1 and i + 1 < len(line):
                last_safe = i + 1
            continue
        if ch in _CLOSE_BRACKETS:
            depth -= 1
            continue
        if ch == "," and depth >= 1 and i + 1 < len(line):
            # Only count this split if it leaves us with a usable next
            # column — i.e. there is something after the comma worth
            # putting on the new line.
            if i + 1 <= width:
                last_safe = i + 1
    return last_safe


def wrap_code(text: str, width: int = 110) -> str:
    """Wrap long source-code lines for the PDF in a way that survives
    copy-paste.  Strategy:

      * Lines short enough are passed through untouched.
      * For long lines, we look for a Python-safe split point — inside
        a paren/bracket group, after a comma — and break there.  Python
        accepts those breaks as implicit line continuation, so a reader
        copying the rendered code into a `.py` file gets working code.
      * If no safe split exists (long string literal, runaway comment),
        the original line is kept intact.  ReportLab will soft-wrap it
        for display, and the raw text in the PDF remains the original
        single line — copy still yields the original.
    """
    out: list[str] = []
    for line in text.splitlines() or [""]:
        if len(line) <= width:
            out.append(line)
            continue
        # Try to find a Python-aware safe split.
        cut = _safe_split_point(line[:width + 1], width)
        if cut is not None and cut > 0:
            indent_match = re.match(r"^(\s*)", line)
            base_indent = indent_match.group(1) if indent_match else ""
            head = line[:cut].rstrip()
            tail = line[cut:].lstrip()
            out.append(head)
            # Hanging indent: 4 spaces past the original indent.
            out.append(base_indent + "    " + tail)
            continue
        # No safe Python break — leave the line alone.  Long string
        # literals, URLs, very long comments etc. fall here.  Copy still
        # works; the PDF may just truncate the visible end of the line.
        out.append(line)
    return "\n".join(out)


def callout_table(content_flowables: list, doc_width: float, kind: str = "blue"):
    """Render a colored callout box with a left-edge accent bar — the
    same look used in the 'Python: The Greatest Hits' format.

    kind="blue"   — informational (lighter blue tint, blue accent)
    kind="orange" — exercise / try-it-yourself (peach tint, orange accent)
    kind="grey"   — neutral (kept for backwards compatibility)
    """
    if kind == "orange":
        bg = colors.HexColor("#fef3e7")
        border = colors.HexColor("#dd6b20")
    elif kind == "grey":
        bg = colors.HexColor("#f7fafc")
        border = colors.HexColor("#a0aec0")
    else:  # blue (default)
        bg = colors.HexColor("#ebf4ff")
        border = colors.HexColor("#3182ce")
    t = Table([[content_flowables]], colWidths=[doc_width - 0.2 * inch])
    t.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, -1), bg),
        ("LINEBEFORE", (0, 0), (0, 0), 3, border),
        ("LEFTPADDING", (0, 0), (-1, -1), 14),
        ("RIGHTPADDING", (0, 0), (-1, -1), 14),
        ("TOPPADDING", (0, 0), (-1, -1), 12),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 12),
    ]))
    return t


def on_page(canvas, doc):
    canvas.saveState()
    page_num = canvas.getPageNumber()
    if page_num > 1:
        canvas.setFont("Helvetica", 8.5)
        canvas.setFillColor(colors.HexColor("#a0aec0"))
        canvas.drawString(
            0.85 * inch, 0.45 * inch,
            "MT5HedgingEngine — Reading Python Through a Real Codebase",
        )
        canvas.drawRightString(
            LETTER[0] - 0.85 * inch, 0.45 * inch, str(page_num),
        )
    canvas.restoreState()


def synopsis_for(m: dict) -> str:
    """Build a short prose synopsis of a module from its name + AST."""
    rel = m["path"].relative_to(REPO_ROOT).as_posix()
    name = m["path"].name
    pieces = []

    hint = FILE_HINTS.get(name)
    if hint:
        pieces.append(hint)
    elif name.startswith("__init__"):
        pieces.append(
            "Package marker. Importing this folder as a module runs the "
            "code here (often empty, sometimes used to re-export public "
            "names)."
        )
    elif "/signals/" in rel and name not in ("__init__.py", "rsi.py"):
        pieces.append(
            "Single-indicator module — see the signals folder note above. "
            "Most of the work is a pandas computation feeding off OHLC bars."
        )

    cls_count = len(m["classes"])
    fn_count = len(m["functions"])
    summary_bits: list[str] = []
    if cls_count and fn_count:
        summary_bits.append(
            f"It defines <b>{cls_count}</b> class{'es' if cls_count != 1 else ''} "
            f"and <b>{fn_count}</b> module-level function"
            f"{'s' if fn_count != 1 else ''}"
        )
    elif cls_count:
        summary_bits.append(
            f"It defines <b>{cls_count}</b> class{'es' if cls_count != 1 else ''}"
        )
    elif fn_count:
        summary_bits.append(
            f"It defines <b>{fn_count}</b> module-level function"
            f"{'s' if fn_count != 1 else ''}"
        )
    summary_bits.append(f"across <b>{m['loc']:,}</b> lines")
    pieces.append(", ".join(summary_bits) + ".")

    if m["doc"]:
        first = first_line(m["doc"])
        if first and first not in pieces[0]:
            pieces.append(f"Module docstring: <i>{esc(first)}</i>")

    return " ".join(pieces)


def render_concept_callout(features: set[str], styles, doc_width: float):
    if not features:
        return None
    items = []
    items.append(Paragraph(
        "<b>Python concepts demonstrated in this module</b>", styles["body"],
    ))
    bullets = []
    for key in sorted(features):
        title = CONCEPT_TITLES.get(key, key.replace("_", " "))
        bullets.append("&bull; " + esc(title))
    items.append(Paragraph("&nbsp;&nbsp;".join(bullets), styles["callout"]))
    return callout_table(items, doc_width)


def render_module(story: list, m: dict, styles, doc_width: float, signals_note_done: list):
    rel = m["path"].relative_to(REPO_ROOT).as_posix()
    story.append(Paragraph(esc(rel), styles["h2"]))
    story.append(Paragraph(
        f"{m['loc']} loc &middot; {len(m['classes'])} classes &middot; "
        f"{len(m['functions'])} functions &middot; "
        f"{len(m['imports'])} imports",
        styles["muted"],
    ))

    if m.get("parse_error"):
        story.append(Paragraph(
            f"<i>Could not parse: {esc(m['parse_error'])}</i>",
            styles["muted"],
        ))
        return

    # Signals folder one-time note
    if "/signals/" in rel and not signals_note_done[0]:
        story.append(callout_table(
            [Paragraph("<b>About the signals folder</b>", styles["body"]),
             Paragraph(SIGNAL_FOLDER_NOTE, styles["body"])],
            doc_width,
        ))
        story.append(Spacer(1, 0.08 * inch))
        signals_note_done[0] = True

    # Synopsis
    story.append(Paragraph(synopsis_for(m), styles["body"]))

    # Module docstring (full — no character cap)
    if m["doc"]:
        body = m["doc"]
        story.append(Paragraph("<b>Module docstring</b>", styles["h3"]))
        for para in body.split("\n\n"):
            para = para.strip().replace("\n", " ")
            if para:
                story.append(Paragraph(esc(para), styles["doc"]))

    # Concepts callout
    callout = render_concept_callout(m["features"], styles, doc_width)
    if callout is not None:
        story.append(callout)
        story.append(Spacer(1, 0.06 * inch))

    # Rich per-import section
    records = m.get("import_records") or []
    if records:
        story.append(Paragraph("<b>Imports — what each one is for</b>", styles["h3"]))
        # Group adjacent from-imports from the same module so we don't
        # repeat the "Why" four times in a row.
        grouped: list[dict] = []
        for r in records:
            if (
                grouped
                and r["kind"] == "from"
                and grouped[-1]["kind"] == "from"
                and grouped[-1]["top"] == r["top"]
                and grouped[-1]["full"] == r["full"]
            ):
                grouped[-1]["lines"].append(r["line"])
                grouped[-1]["used"].extend(r["used"])
            else:
                grouped.append({
                    "lines": [r["line"]],
                    "kind": r["kind"],
                    "top": r["top"],
                    "full": r["full"],
                    "used": list(r["used"]),
                    "kb": r["kb"],
                })

        for g in grouped:
            story.append(Preformatted(
                wrap_code("\n".join(g["lines"])), styles["code"]),
            )
            kb = g["kb"]
            if kb is not None:
                story.append(Paragraph(
                    f"&nbsp;&nbsp;<b>Why imported.</b> {kb['why']}",
                    styles["doc"],
                ))
            else:
                story.append(Paragraph(
                    f"&nbsp;&nbsp;<b>Why imported.</b> "
                    f"<i>{esc(g['top'] or g['full'] or '?')}</i> — module "
                    "specific to this codebase. See the chapter that "
                    "covers its source for the full definition.",
                    styles["doc"],
                ))
            if g["used"]:
                used_unique = sorted(set(g["used"]))[:12]
                more = ""
                if len(set(g["used"])) > 12:
                    more = f" &hellip; (+{len(set(g['used'])) - 12} more)"
                story.append(Paragraph(
                    f"&nbsp;&nbsp;<b>Used in this file.</b> "
                    f"<code>{esc(', '.join(used_unique))}</code>{more}",
                    styles["doc"],
                ))
            else:
                story.append(Paragraph(
                    "&nbsp;&nbsp;<b>Used in this file.</b> "
                    "<i>No direct attribute access detected — likely "
                    "imported for side effects, re-export, or string "
                    "references.</i>",
                    styles["doc"],
                ))
            if kb and kb.get("example"):
                story.append(Paragraph(
                    f"&nbsp;&nbsp;<b>Example.</b> "
                    f"<code>{esc(kb['example'])}</code>",
                    styles["doc"],
                ))
            if kb and kb.get("others"):
                story.append(Paragraph(
                    "&nbsp;&nbsp;<b>Other common scenarios.</b>",
                    styles["doc"],
                ))
                for s in kb["others"]:
                    story.append(Paragraph(
                        f"&nbsp;&nbsp;&nbsp;&nbsp;&bull; {esc(s)}",
                        styles["doc"],
                    ))
            story.append(Spacer(1, 0.05 * inch))

    if m["constants"]:
        story.append(Paragraph("<b>Module constants</b>", styles["h3"]))
        story.append(Paragraph(
            "Each line below is followed by a plain-English note "
            "explaining what it does and why it is written that way.",
            styles["muted"],
        ))
        # Show every constant — no cap.  The reader gets the complete
        # picture of the module's top-level state.
        for const_line in m["constants"]:
            story.append(Preformatted(
                wrap_code(const_line), styles["code"],
            ))
            note = explain_constant(const_line)
            if note:
                story.append(Paragraph(
                    f"&nbsp;&nbsp;{note}", styles["doc"],
                ))
            story.append(Spacer(1, 0.03 * inch))

    if m["classes"]:
        story.append(Paragraph("<b>Classes</b>", styles["h3"]))
        for c in m["classes"]:
            header = f"class {c['name']}"
            if c["bases"]:
                header += "(" + ", ".join(c["bases"]) + ")"
            inner: list = []
            for d in c["decorators"]:
                inner.append(Preformatted(wrap_code(d), styles["code"]))
            inner.append(Preformatted(wrap_code(header), styles["code"]))
            if c["doc"]:
                doc = c["doc"]
                inner.append(Paragraph(
                    "<i>" + esc(doc.replace("\n", " ")) + "</i>",
                    styles["doc"],
                ))
            if c["attrs"]:
                inner.append(Preformatted(
                    wrap_code("\n".join(c["attrs"])),
                    styles["code"],
                ))
            # Class header excerpt: shows decorators, bases, and the
            # first ~25 lines of the class body so the reader sees
            # context before we drill into individual methods.
            render_excerpt(inner, c, styles)
            for meth in c["methods"]:
                # Method signature is rendered without a forced "    "
                # indent prefix — we want the reader to be able to copy
                # the signature line straight into a class body.  The
                # heading below tells them which class it belongs to.
                inner.append(Paragraph(
                    f"<b>Method:</b> <code>{esc(c['name'])}.{esc(meth['name'])}</code>",
                    styles["body_left"],
                ))
                inner.append(Preformatted(
                    wrap_code(meth["signature"]), styles["code"],
                ))
                if meth["doc"]:
                    md = meth["doc"]
                    inner.append(Paragraph(
                        "<i>" + esc(md.replace("\n", " ")) + "</i>",
                        styles["doc"],
                    ))
                render_rationales(inner, meth, styles, indent_em=0)
                render_steps(inner, meth, styles, indent_em=0)
                render_excerpt(inner, meth, styles)
                inner.append(Spacer(1, 0.06 * inch))
            story.extend(inner)
            story.append(Spacer(1, 0.08 * inch))

    if m["functions"]:
        story.append(Paragraph("<b>Functions</b>", styles["h3"]))
        for fn in m["functions"]:
            story.append(Preformatted(wrap_code(fn["signature"]), styles["code"]))
            if fn["doc"]:
                fd = fn["doc"]
                story.append(Paragraph(
                    "&nbsp;&nbsp;<i>" + esc(fd.replace("\n", " ")) + "</i>",
                    styles["doc"],
                ))
            render_rationales(story, fn, styles, indent_em=2)
            render_steps(story, fn, styles, indent_em=2)
            render_excerpt(story, fn, styles)
            story.append(Spacer(1, 0.08 * inch))
        story.append(Spacer(1, 0.08 * inch))


# ---------------------------------------------------------------------------
# 4b.  Frontend rendering — per-template section + chapter builder
# ---------------------------------------------------------------------------


def render_template_block(story: list, t: dict, styles, doc_width: float):
    """Render one template as its own subsection inside the frontend
    chapter.  Mirrors render_module's shape so the book reads
    consistently."""
    rel = t["path"].relative_to(REPO_ROOT).as_posix()
    name = t["path"].name
    story.append(Paragraph(esc(rel), styles["h2"]))
    story.append(Paragraph(
        f"{t['loc']:,} loc &middot; {t['bytes']:,} bytes &middot; "
        f"{t['n_interp']} <code>{{{{ ... }}}}</code> expressions "
        f"&middot; {t['n_for']} <code>for</code> loops &middot; "
        f"{t['n_if']} <code>if</code> blocks",
        styles["muted"],
    ))

    hint = TEMPLATE_HINTS.get(name)
    if hint:
        story.append(Paragraph(hint, styles["body"]))

    # Inheritance / composition
    if t["extends"]:
        story.append(Paragraph(
            f"<b>Inherits from</b> <code>{esc(t['extends'])}</code> "
            "— meaning Jinja loads that parent template first, then "
            "overrides the named blocks below.",
            styles["body_left"],
        ))
    else:
        story.append(Paragraph(
            "<b>Standalone template</b> — does not extend a parent. "
            "The full HTML document lives inside this single file.",
            styles["body_left"],
        ))
    if t["blocks"]:
        story.append(Paragraph(
            f"<b>Blocks defined.</b> "
            f"<code>{esc(', '.join(t['blocks']))}</code>. Child "
            "templates can override these; if no child does, the "
            "default content rendered here is what the user sees.",
            styles["doc"],
        ))
    if t["includes"]:
        story.append(Paragraph(
            f"<b>Includes.</b> "
            f"<code>{esc(', '.join(t['includes']))}</code> &mdash; "
            "shared partials pulled in inline at render time.",
            styles["doc"],
        ))
    if t["url_for"]:
        sample = t["url_for"][:14]
        more = ""
        if len(t["url_for"]) > 14:
            more = f" &hellip; (+{len(t['url_for']) - 14} more)"
        story.append(Paragraph(
            f"<b>Routes referenced via <code>url_for(...)</code>.</b> "
            f"<code>{esc(', '.join(sample))}</code>{more}. Each entry "
            "is a Flask endpoint name — search for the matching "
            "<code>@app.route</code> or <code>@bp.route</code> "
            "decorator in <code>dashboard/app.py</code>.",
            styles["doc"],
        ))
    if t["forms"]:
        items = []
        for action, method in t["forms"][:6]:
            items.append(
                f"{(method or 'GET').upper()} &rarr; "
                f"<code>{esc(action or '(self)')}</code>"
            )
        more = ""
        if len(t["forms"]) > 6:
            more = f" (+{len(t['forms']) - 6} more)"
        story.append(Paragraph(
            f"<b>Forms.</b> {' &middot; '.join(items)}{more}. The "
            "server route at the receiving end validates inputs and "
            "redirects on success.",
            styles["doc"],
        ))

    if t["ui_libs"]:
        story.append(Paragraph(
            f"<b>UI libraries detected.</b> "
            f"<code>{esc(', '.join(t['ui_libs']))}</code>. Loaded via "
            "either a CDN <code>&lt;script&gt;</code> tag or a local "
            "static asset.",
            styles["doc"],
        ))
    if t["ajax"]:
        story.append(Paragraph(
            f"<b>AJAX patterns detected.</b> "
            f"<code>{esc(', '.join(t['ajax']))}</code>. The page is "
            "not purely server-rendered: parts of it talk back to "
            "Flask routes from the browser after the initial load.",
            styles["doc"],
        ))

    flags: list[str] = []
    if t["uses_csrf"]:
        flags.append("uses <code>csrf_token()</code> (Flask-WTF wired in)")
    if t["uses_current_user"]:
        flags.append("reads <code>current_user</code> (Flask-Login auth-aware)")
    if t["uses_flashes"]:
        flags.append("renders <code>get_flashed_messages()</code> (flash banner)")
    if t["n_scripts"]:
        flags.append(
            f"{t['n_scripts']} inline <code>&lt;script&gt;</code> block"
            f"{'s' if t['n_scripts'] != 1 else ''}"
        )
    if t["n_styles"]:
        flags.append(
            f"{t['n_styles']} inline <code>&lt;style&gt;</code> block"
            f"{'s' if t['n_styles'] != 1 else ''}"
        )
    if t["external_scripts"]:
        flags.append(
            f"{len(t['external_scripts'])} external script"
            f"{'s' if len(t['external_scripts']) != 1 else ''}"
        )
    if flags:
        story.append(Paragraph(
            "<b>Notes.</b> " + " &middot; ".join(flags) + ".",
            styles["doc"],
        ))

    if t["external_scripts"]:
        sample = t["external_scripts"][:6]
        more = ""
        if len(t["external_scripts"]) > 6:
            more = f"\n... (+{len(t['external_scripts']) - 6} more)"
        story.append(Paragraph(
            "&nbsp;&nbsp;<b>External scripts loaded.</b>", styles["doc"],
        ))
        story.append(Preformatted(
            wrap_code("\n".join(sample) + more), styles["code"],
        ))

    # First 30 lines of the template — gives the reader a feel for the
    # actual markup before they crack the file open.
    story.append(Paragraph(
        "<b>Opening of the template:</b>", styles["doc"],
    ))
    story.append(Preformatted(
        wrap_code(t["excerpt"]), styles["code"],
    ))
    story.append(Spacer(1, 0.12 * inch))


def build_frontend_chapter(
    story: list, styles, doc_width: float, chap_no: int,
    templates: list[dict], static_info: dict,
) -> None:
    """A whole chapter dedicated to the user-facing layer.  Sits
    between the Python build phases and the closing glossary."""

    story.append(Paragraph(
        f"Chapter {chap_no} — The frontend: templates, CSS, and the "
        "JavaScript glue",
        styles["chapter"],
    ))
    story.append(Paragraph(
        "Up to this point the book has been about Python — the request "
        "router, the database layer, the prop-firm integrations, the "
        "trader desktop app. This chapter is about the layer the user "
        "actually sees: Flask templates, the CSS that styles them, and "
        "the JavaScript embedded inside them. None of it is in a "
        "separate single-page-app: every page is server-rendered "
        "Jinja2, with progressive enhancement bolted on via inline "
        "<code>&lt;script&gt;</code> blocks.",
        styles["body"],
    ))
    story.append(Paragraph(
        "That is a deliberate, slightly old-school choice. It means "
        "the dashboard works without a build step, a developer can "
        "read a page top to bottom without bouncing between framework "
        "files, and the same template that renders the page can also "
        "be the file you grep when something looks wrong. It costs us "
        "the SPA niceties (instant route changes, shared client "
        "state), but for a back-office dashboard the trade is fair.",
        styles["body"],
    ))

    # ---- Jinja primer ----
    story.append(Paragraph("How Flask templating works", styles["h1"]))
    story.append(Paragraph(
        "Flask uses <b>Jinja2</b> as its templating engine. Three "
        "mustache-flavoured constructs do the heavy lifting:",
        styles["body"],
    ))
    story.append(Paragraph(
        "&bull; <code>{{ expression }}</code> &mdash; an "
        "<i>expression</i>: evaluate the Python expression inside the "
        "double braces and substitute the (HTML-escaped) result. "
        "This is how you print a variable.",
        styles["doc"],
    ))
    story.append(Paragraph(
        "&bull; <code>{% statement %}</code> &mdash; a <i>statement</i>: "
        "control flow. <code>{% if user.is_admin %} ... {% endif %}</code>, "
        "<code>{% for client in clients %} ... {% endfor %}</code>, "
        "<code>{% extends 'base.html' %}</code>, "
        "<code>{% block title %}{% endblock %}</code>, "
        "<code>{% include 'sidebar.html' %}</code>.",
        styles["doc"],
    ))
    story.append(Paragraph(
        "&bull; <code>{# comment #}</code> &mdash; a Jinja comment that "
        "is stripped before the HTML reaches the browser (unlike "
        "<code>&lt;!-- ... --&gt;</code>, which is sent and visible to "
        "anyone using View Source).",
        styles["doc"],
    ))
    story.append(Paragraph(
        "Inheritance is the trick that keeps things DRY. A parent "
        "template lays out the shell (header, nav, footer) and "
        "declares named <code>{% block %}</code> regions. Child "
        "templates do <code>{% extends 'parent.html' %}</code> and "
        "override only the blocks they care about. Read every "
        "<i>Inherits from</i> note below as: this child page reuses "
        "the parent's shell and only customises the named blocks.",
        styles["body"],
    ))
    story.append(Paragraph(
        "Two helpers you will see referenced over and over:",
        styles["body"],
    ))
    story.append(Paragraph(
        "&bull; <code>url_for('endpoint_name')</code> &mdash; resolve a "
        "named Flask route into an actual URL at render time. Using "
        "this instead of hard-coding <code>'/login'</code> means "
        "moving a route is a one-line change in <code>app.py</code>, "
        "not a project-wide find-and-replace.",
        styles["doc"],
    ))
    story.append(Paragraph(
        "&bull; <code>csrf_token()</code> &mdash; emits the CSRF token "
        "for forms protected by Flask-WTF. The server rejects POSTs "
        "where the token is missing or wrong; this is what blocks "
        "third-party sites from forging requests on behalf of a "
        "logged-in user.",
        styles["doc"],
    ))

    # ---- A summary table of all templates ----
    story.append(PageBreak())
    story.append(Paragraph(
        "All templates at a glance", styles["h1"],
    ))
    story.append(Paragraph(
        "Sorted by size. Use this as the chapter's table of "
        "contents — the bigger the template, the more of the user's "
        "actual experience lives inside it.",
        styles["body"],
    ))
    rows = [["Template", "LOC", "Bytes", "Forms", "Scripts", "Routes"]]
    for t in sorted(templates, key=lambda x: -x["loc"]):
        rel = t["path"].relative_to(REPO_ROOT / "dashboard" / "templates").as_posix()
        rows.append([
            rel,
            f"{t['loc']:,}",
            f"{t['bytes']:,}",
            str(len(t["forms"])),
            str(t["n_scripts"]),
            str(len(t["url_for"])),
        ])
    tbl = Table(rows, hAlign="LEFT", colWidths=[2.4 * inch, 0.7 * inch,
                                                0.9 * inch, 0.6 * inch,
                                                0.7 * inch, 0.7 * inch])
    tbl.setStyle(TableStyle([
        ("FONT", (0, 0), (-1, 0), "Helvetica-Bold", 9),
        ("FONT", (0, 1), (-1, -1), "Helvetica", 8),
        ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#edf2f7")),
        ("LINEBELOW", (0, 0), (-1, 0), 0.5, colors.HexColor("#cbd5e0")),
        ("ROWBACKGROUNDS", (0, 1), (-1, -1),
         [colors.white, colors.HexColor("#f7fafc")]),
        ("TOPPADDING", (0, 0), (-1, -1), 3),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 3),
    ]))
    story.append(tbl)
    story.append(Spacer(1, 0.15 * inch))

    # ---- Group templates by audience ----
    groups = [
        ("Public &amp; auth pages — what an unauthenticated visitor sees",
         ["login.html", "change_password.html", "maintenance.html",
          "500.html"],
         "These four templates are the only ones an unauthenticated or "
         "error-state user can reach. They are intentionally small and "
         "self-contained: when the rest of the app is broken, these "
         "are still expected to render."),
        ("Admin &amp; super-admin views — the operations layer",
         ["admin_dashboard.html", "super_admin.html", "hierarchy.html",
          "client_management.html"],
         "These are the templates that the people running the desk "
         "spend their day inside. Heavier on tables, modals, and "
         "click-to-edit forms than on visualisations."),
        ("Trader-facing views",
         ["trader_dashboard.html", "trader_performance.html"],
         "What a trader sees when they sign in. The trader-facing "
         "equivalent of the admin dashboard, scoped to their own "
         "clients and accounts."),
        ("Client-facing &amp; financial views",
         ["client_performance.html", "financial_overview.html",
          "payout_history.html"],
         "The money pages: per-client breakdowns, the cross-org "
         "financial overview, and the payout audit log. The numbers "
         "shown here are what conversations with the trader and the "
         "prop firm hinge on."),
        ("Quality &amp; tooling",
         ["quality_dashboard.html"],
         "The data-quality dashboard. This is where the team finds out "
         "whether the ingestion pipelines actually loaded what they "
         "were supposed to load."),
        ("Other",
         ["index.html"],
         "The landing template. Despite the name, this file does not "
         "render the literal home URL — Flask routes pick which "
         "template to render based on the user's role. This is the "
         "fallback that holds the dashboard widgets shared across "
         "roles."),
    ]
    by_name = {t["path"].name: t for t in templates}
    rendered: set[str] = set()
    for title, names, intro in groups:
        story.append(PageBreak())
        story.append(Paragraph(title, styles["h1"]))
        story.append(Paragraph(intro, styles["body"]))
        for nm in names:
            t = by_name.get(nm)
            if t is None:
                continue
            render_template_block(story, t, styles, doc_width)
            rendered.add(nm)

    # Any template we didn't pre-categorise still gets rendered.
    leftover = [t for t in templates if t["path"].name not in rendered]
    if leftover:
        story.append(PageBreak())
        story.append(Paragraph("Other templates", styles["h1"]))
        for t in leftover:
            render_template_block(story, t, styles, doc_width)

    # ---- CSS section ----
    story.append(PageBreak())
    story.append(Paragraph(
        "The CSS layer", styles["h1"],
    ))
    story.append(Paragraph(
        "All custom styling lives in <code>dashboard/static/css/</code>. "
        "There is no preprocessor (Sass, Less) and no PostCSS pipeline "
        "— this is plain CSS, served as-is by Flask's static handler. "
        "That keeps the deploy story simple at the cost of a slightly "
        "longer single file.",
        styles["body"],
    ))
    if static_info["css_files"]:
        for css in static_info["css_files"]:
            rel = css["path"].relative_to(REPO_ROOT).as_posix()
            story.append(Paragraph(esc(rel), styles["h2"]))
            story.append(Paragraph(
                f"{css['loc']:,} loc &middot; {css['bytes']:,} bytes "
                f"&middot; ~{css['n_rules']:,} rules &middot; "
                f"{css['n_media']} <code>@media</code> queries "
                f"&middot; {css['n_keyframes']} <code>@keyframes</code> "
                f"animations &middot; {css['n_vars']} CSS custom "
                "properties",
                styles["muted"],
            ))
            note = (
                "A single concatenated stylesheet shared across every "
                "template. The inline <code>&lt;style&gt;</code> "
                "blocks in individual templates layer on top for "
                "page-specific tweaks."
            )
            if css["n_vars"] > 0:
                note += (
                    f" The {css['n_vars']} CSS custom properties (the "
                    "<code>--name: value</code> declarations) are how "
                    "the dashboard themes itself: change one variable "
                    "at the <code>:root</code> level and every rule "
                    "that references it updates."
                )
            story.append(Paragraph(note, styles["body"]))

    # ---- Static HTML (maintenance.html, etc.) ----
    if static_info["static_html"]:
        story.append(Paragraph(
            "Static HTML (no Flask, no Jinja)", styles["h2"],
        ))
        story.append(Paragraph(
            "A few HTML files live under <code>dashboard/static/</code> "
            "directly. These are served as plain files — Flask never "
            "templates them. Useful for pages that must render even "
            "when the Flask app itself is unreachable.",
            styles["body"],
        ))
        for p in static_info["static_html"]:
            rel = p.relative_to(REPO_ROOT).as_posix()
            story.append(Paragraph(
                f"&bull; <code>{esc(rel)}</code>", styles["doc"],
            ))

    # ---- Closing aside ----
    story.append(Spacer(1, 0.15 * inch))
    story.append(callout_table([
        Paragraph("<b>How a request actually flows</b>", styles["body"]),
        Paragraph(
            "Worth tracing in your head once. A user clicks a link to "
            "<code>/clients/42</code>. Gunicorn (production) or "
            "Flask's dev server (local) accepts the TCP connection "
            "and hands it to <code>wsgi.py</code>, which exposes the "
            "Flask <code>app</code> object built in "
            "<code>dashboard/app.py</code>. Flask matches the URL "
            "against its registered routes, finds the handler, and "
            "calls it. The handler queries the database via "
            "SQLAlchemy, builds a context dictionary, and returns "
            "<code>render_template('client_performance.html', "
            "**context)</code>. Jinja loads the template, walks the "
            "<code>{% extends %}</code> chain, runs every "
            "<code>{{ expression }}</code> against the context, and "
            "produces the final HTML string. Flask wraps it in a "
            "<code>200</code> response and ships it back. The browser "
            "loads the inline JavaScript, which fires its own "
            "<code>fetch()</code> calls back to other Flask routes "
            "for the live charts. That last step is the only place "
            "where the two halves of the app meet asynchronously.",
            styles["body"],
        ),
    ], doc_width))


# ---------------------------------------------------------------------------
# 5.  Story building (book structure)
# ---------------------------------------------------------------------------


def build_story(
    modules: list[dict], styles, doc_width: float,
    templates: list[dict] | None = None,
    static_info: dict | None = None,
) -> list:
    if templates is None:
        templates = []
    if static_info is None:
        static_info = {"css_files": [], "static_html": []}
    story: list = []

    # ---- Cover ----
    story.append(Spacer(1, 1.6 * inch))
    story.append(Paragraph("MT5HedgingEngine", styles["title"]))
    story.append(Paragraph(
        "Build a real Python trading platform from scratch — "
        "a step-by-step walkthrough of every file, every class, "
        "every function, with the actual source code inline.",
        styles["subtitle"],
    ))
    story.append(Spacer(1, 0.4 * inch))

    total_loc = sum(m["loc"] for m in modules)
    total_cls = sum(len(m["classes"]) for m in modules)
    total_meth = sum(len(c["methods"]) for m in modules for c in m["classes"])
    total_fn = sum(len(m["functions"]) for m in modules)

    story.append(Paragraph(
        f"This book teaches you to build the MT5HedgingEngine project "
        f"end-to-end. We will create {len(modules)} Python files together "
        f"— {total_loc:,} lines of code, {total_cls:,} classes "
        f"({total_meth:,} methods), and {total_fn:,} module-level "
        f"functions — in the dependency-correct order a working "
        f"developer would build them.",
        styles["body"],
    ))
    story.append(PageBreak())

    # ---- Foreword ----
    story.append(Paragraph("Foreword — who this book is for", styles["chapter"]))
    story.append(Paragraph(
        "This book is for someone who knows a little Python — enough to "
        "open a REPL, write a function, and run a script — but has "
        "never built anything as large as a real trading platform. By "
        "the time you finish, you will have built one yourself, file by "
        "file, in the same order the original authors did, and you will "
        "understand why every line is the way it is.",
        styles["body"],
    ))
    story.append(Paragraph(
        "The platform you will build does three things. First, it talks "
        "to MetaTrader 5 — a broker terminal — through MetaQuotes' "
        "official Python API: places orders, reads tick history, "
        "monitors open positions. Second, it scrapes prop-firm dashboards "
        "(Topstep, FundedNext, Tradovate, TradeOpss) using browser "
        "automation, because most prop firms have no public API. Third, "
        "it serves a Flask web dashboard where admins, managers and "
        "traders can see account state, payouts, and performance. A "
        "Tkinter desktop window ties the trader-side pieces together.",
        styles["body"],
    ))
    story.append(Paragraph(
        "How the book is organised:",
        styles["body_left"],
    ))
    story.append(Paragraph(
        "&bull; <b>Chapter 1</b> walks you through getting a working "
        "Python development environment — installing Python, creating a "
        "virtual environment, the project folder layout, the "
        "<code>requirements.txt</code> file, the <code>.env</code> file, "
        "and the external pieces (MetaTrader 5 terminal, Chrome) you "
        "need on your machine.",
        styles["doc"],
    ))
    story.append(Paragraph(
        "&bull; <b>Chapter 2</b> is a primer on the Python language "
        "features the rest of the book uses. Read it cover-to-cover or "
        "skim for unfamiliar names — you can come back to it whenever a "
        "later chapter mentions something you do not recognise.",
        styles["doc"],
    ))
    story.append(Paragraph(
        "&bull; <b>Chapters 3 through 12</b> are the build itself, "
        "split into ten <i>phases</i>. Phase 1 is the boring foundation "
        "(settings, helpers); Phase 10 is the deployment scripts that "
        "ship the finished thing. Each phase opens with a one-page "
        "intro that tells you what you are about to build and why it "
        "comes next, then walks each file in order. Every class, every "
        "method, and every function gets four things: the source code "
        "itself, an explanation of which Python concepts it uses and "
        "why those were the right tools, a numbered step-by-step "
        "walkthrough of the body, and the function's own docstring "
        "where one exists.",
        styles["doc"],
    ))
    story.append(Paragraph(
        "&bull; The <b>frontend chapter</b> picks up where the Python "
        "phases leave off and walks the user-facing layer: every Jinja "
        "template under <code>dashboard/templates/</code>, the static "
        "CSS under <code>dashboard/static/</code>, and the embedded "
        "JavaScript that gives each page its interactivity. Every "
        "template gets a stat block (LOC, expressions, forms, AJAX "
        "patterns), a one-line purpose, and the first ~30 lines of "
        "actual markup so you can read along.",
        styles["doc"],
    ))
    story.append(Paragraph(
        "&bull; The <b>closing chapter</b> is a glossary plus a concept "
        "index — if you want to see real working examples of, say, "
        "decorators or generators or context managers, the index lists "
        "every module that uses each one.",
        styles["doc"],
    ))
    story.append(Paragraph(
        "<b>How to use the book.</b> Type the code in. Don't just read "
        "it. The whole point of building a project from scratch is that "
        "the muscle memory and the small surprises (a missing import, "
        "a typo in a config key, a mis-named column) are what teach "
        "you. The pages give you the destination; you take the steps. "
        "If something does not work, the right reaction is curiosity, "
        "not frustration — every error message is a piece of the "
        "language teaching you something specific.",
        styles["body"],
    ))
    story.append(PageBreak())

    # ---- Table of contents ----
    story.append(Paragraph("Table of contents", styles["chapter"]))
    story.append(Paragraph("Foreword — who this book is for", styles["tocchap"]))
    story.append(Paragraph("Chapter 1 — Project setup", styles["tocchap"]))
    story.append(Paragraph(
        "Chapter 2 — Python concepts: a primer", styles["tocchap"],
    ))
    for c in CONCEPTS_PRIMER:
        story.append(Paragraph("&bull; " + esc(c["title"]), styles["tocfile"]))

    phased = order_modules_by_phase(modules)
    chap = 3
    for phase, files in phased:
        story.append(Paragraph(
            f"Chapter {chap} — {esc(phase['title'])}", styles["tocchap"],
        ))
        for m in files:
            rel = m["path"].relative_to(REPO_ROOT).as_posix()
            label = (
                f"{esc(rel)} &nbsp;&nbsp;"
                f"<font color='#a0aec0'>"
                f"({m['loc']} loc, {len(m['classes'])}c, "
                f"{len(m['functions'])}f)</font>"
            )
            story.append(Paragraph(label, styles["tocfile"]))
        chap += 1
    if templates:
        story.append(Paragraph(
            f"Chapter {chap} — The frontend: templates, CSS, and the "
            "JavaScript glue", styles["tocchap"],
        ))
        for t in sorted(templates, key=lambda x: -x["loc"]):
            rel = t["path"].relative_to(
                REPO_ROOT / "dashboard" / "templates"
            ).as_posix()
            story.append(Paragraph(
                f"{esc(rel)} &nbsp;&nbsp;"
                f"<font color='#a0aec0'>({t['loc']:,} loc, "
                f"{len(t['forms'])} form"
                f"{'s' if len(t['forms']) != 1 else ''})</font>",
                styles["tocfile"],
            ))
        chap += 1
    story.append(Paragraph(
        f"Chapter {chap} — Glossary &amp; concept index",
        styles["tocchap"],
    ))
    story.append(PageBreak())

    # ---- Chapter 1: Project setup ----
    story.append(Paragraph("Chapter 1 — Project setup", styles["chapter"]))
    story.append(Paragraph(
        "Before we write a single line of project code, we need a "
        "working development environment. This chapter is all setup — "
        "by the end of it you will have an empty project folder with "
        "Python, a virtual environment, the dependencies installed, "
        "and the external tools (MT5 terminal, Chrome) ready to go.",
        styles["body"],
    ))

    story.append(Paragraph("1.1  Install Python", styles["h2"]))
    story.append(Paragraph(
        "Download Python 3.10 or newer from "
        "<i>python.org/downloads</i>. On Windows, tick the <i>Add "
        "Python to PATH</i> checkbox during install — without it, the "
        "<code>python</code> command will not be on your terminal's "
        "path. Verify the install by opening a fresh terminal and "
        "running:",
        styles["body"],
    ))
    story.append(Preformatted("python --version", styles["code"]))
    story.append(Paragraph(
        "You should see <code>Python 3.10.x</code> or newer. If you see "
        "<code>'python' is not recognised</code>, the PATH did not get "
        "set — re-run the installer and tick the box, or add the Python "
        "folder to your PATH manually.",
        styles["body"],
    ))

    story.append(Paragraph(
        "1.2  Create the project folder", styles["h2"],
    ))
    story.append(Paragraph(
        "Pick a place for the project and create the top-level folder. "
        "Everything we build lives inside this folder.",
        styles["body"],
    ))
    story.append(Preformatted(
        "mkdir MT5HedgingEngine\n"
        "cd MT5HedgingEngine",
        styles["code"],
    ))

    story.append(Paragraph("1.3  Create a virtual environment", styles["h2"]))
    story.append(Paragraph(
        "A virtual environment is an isolated Python install that "
        "belongs to this project. It keeps the project's dependencies "
        "from clashing with anything else on your machine, and it is "
        "the single most useful habit a Python developer can have. "
        "Create and activate one:",
        styles["body"],
    ))
    story.append(Preformatted(
        "python -m venv .venv\n"
        "# Windows:\n"
        ".venv\\Scripts\\activate\n"
        "# macOS / Linux:\n"
        "source .venv/bin/activate",
        styles["code"],
    ))
    story.append(Paragraph(
        "After activation your terminal prompt should start with "
        "<code>(.venv)</code>. Every <code>pip install</code> from now "
        "on lands in this isolated environment, not in the system "
        "Python.",
        styles["body"],
    ))

    story.append(Paragraph("1.4  Create the folder layout", styles["h2"]))
    story.append(Paragraph(
        "We will be building the following structure. Create the empty "
        "folders now — the files inside will be filled in chapter by "
        "chapter.",
        styles["body"],
    ))
    story.append(Preformatted(
        "MT5HedgingEngine/\n"
        "  config/\n"
        "  utils/\n"
        "  connectors/\n"
        "  alembic/\n"
        "    versions/\n"
        "  trader_companion/\n"
        "    signals/\n"
        "    strategies/\n"
        "    utils/\n"
        "  dashboard/\n"
        "    utils/\n"
        "    static/\n"
        "    templates/",
        styles["code"],
    ))
    story.append(Paragraph(
        "Python only treats a folder as an importable <i>package</i> "
        "when it contains an <code>__init__.py</code> file (it can be "
        "empty). For each of the folders above except "
        "<code>static/</code> and <code>templates/</code>, create an "
        "empty <code>__init__.py</code>:",
        styles["body"],
    ))
    story.append(Preformatted(
        "# Windows PowerShell\n"
        "New-Item config/__init__.py, utils/__init__.py, "
        "connectors/__init__.py -ItemType File\n"
        "# macOS / Linux\n"
        "touch config/__init__.py utils/__init__.py connectors/__init__.py",
        styles["code"],
    ))

    story.append(Paragraph("1.5  Write requirements.txt", styles["h2"]))
    story.append(Paragraph(
        "<code>requirements.txt</code> is the manifest of every "
        "third-party package the project depends on. Create it at the "
        "root with this content (the exact versions can be loosened "
        "later, but pinned versions reproduce the exact environment "
        "the original project ran on):",
        styles["body"],
    ))
    story.append(Preformatted(
        "Flask\n"
        "Flask-Login\n"
        "Flask-Limiter\n"
        "SQLAlchemy\n"
        "alembic\n"
        "psycopg2-binary\n"
        "requests\n"
        "pandas\n"
        "numpy\n"
        "MetaTrader5\n"
        "selenium\n"
        "apscheduler\n"
        "python-dotenv\n"
        "werkzeug\n"
        "openpyxl\n"
        "pytz\n"
        "psutil\n"
        "websocket-client\n"
        "gunicorn\n"
        "reportlab",
        styles["code"],
    ))
    story.append(Paragraph(
        "Install them all in one go (this will take a minute or two):",
        styles["body"],
    ))
    story.append(Preformatted(
        "pip install -r requirements.txt",
        styles["code"],
    ))

    story.append(Paragraph("1.6  Create the .env file", styles["h2"]))
    story.append(Paragraph(
        "<i>Twelve-factor configuration</i> says that anything that "
        "differs between dev and production should come from "
        "environment variables, not code. We use a <code>.env</code> "
        "file (loaded by <code>python-dotenv</code>) to keep those "
        "values out of git. Create <code>.env</code> in the project "
        "root with at least these keys:",
        styles["body"],
    ))
    story.append(Preformatted(
        "FLASK_SECRET_KEY=change-me-to-a-long-random-string\n"
        "DATABASE_URL=sqlite:///dashboard.db\n"
        "MT5_LOGIN=\n"
        "MT5_PASSWORD=\n"
        "MT5_SERVER=\n"
        "GOOGLE_SHEETS_CREDS=\n"
        "SMTP_HOST=\n"
        "SMTP_USER=\n"
        "SMTP_PASSWORD=",
        styles["code"],
    ))
    story.append(Paragraph(
        "Add <code>.env</code> to your <code>.gitignore</code> "
        "<b>before</b> the first commit — it is going to hold real "
        "secrets later.",
        styles["body"],
    ))

    story.append(Paragraph("1.7  Install the MetaTrader 5 terminal", styles["h2"]))
    story.append(Paragraph(
        "The <code>MetaTrader5</code> Python package talks to a real "
        "terminal that has to be installed and logged in. Download it "
        "from your broker (or from <i>metatrader5.com</i>), install it, "
        "log in once with your account, and leave it running. The "
        "Python package on its own does nothing — it is a client to "
        "the terminal you just installed.",
        styles["body"],
    ))

    story.append(Paragraph("1.8  Install Chrome (for Selenium)", styles["h2"]))
    story.append(Paragraph(
        "The prop-firm scrapers in Phase 6 drive a real Chrome browser. "
        "Install Chrome if you do not already have it. Modern Selenium "
        "ships with Selenium Manager, which downloads the matching "
        "<code>chromedriver</code> automatically — no extra install "
        "needed.",
        styles["body"],
    ))

    story.append(Paragraph("1.9  Verify the setup", styles["h2"]))
    story.append(Paragraph(
        "Quick sanity check. From the project root, with the venv "
        "active, run:",
        styles["body"],
    ))
    story.append(Preformatted(
        "python -c \"import flask, sqlalchemy, pandas, "
        "MetaTrader5, selenium; print('OK')\"",
        styles["code"],
    ))
    story.append(Paragraph(
        "If you see <code>OK</code>, you are ready. If any of those "
        "imports fails, fix it before moving on — the rest of the book "
        "depends on them.",
        styles["body"],
    ))
    story.append(PageBreak())

    # ---- Chapter 2: Python concepts primer ----
    story.append(Paragraph(
        "Chapter 2 — Python concepts: a primer", styles["chapter"],
    ))
    story.append(Paragraph(
        "A short tour of the language features you will see across the "
        "rest of the book. Each section is brief by design — the goal "
        "is to give you a hook the real code can hang on. When a later "
        "chapter mentions a concept you do not remember, flip back here.",
        styles["body"],
    ))
    for c in CONCEPTS_PRIMER:
        story.append(Paragraph(esc(c["title"]), styles["h2"]))
        story.append(Paragraph(c["body"], styles["body"]))
    story.append(PageBreak())

    # ---- Chapters 3..N: build phases ----
    chap_no = 3
    phase_index = 0
    for phase, files in phased:
        phase_index += 1
        story.append(Paragraph(
            f"Chapter {chap_no} — {esc(phase['title'])}",
            styles["chapter"],
        ))
        story.append(Paragraph(phase["intro"], styles["body"]))
        story.append(Paragraph(
            "<b>Files we build in this phase, in order:</b>",
            styles["body_left"],
        ))
        for m in files:
            rel = m["path"].relative_to(REPO_ROOT).as_posix()
            story.append(Paragraph("&bull; " + esc(rel), styles["doc"]))
        story.append(Spacer(1, 0.1 * inch))

        # Phase concepts callout — what the AST detected across all
        # files in this phase, sorted by frequency.
        phase_feats: Counter = Counter()
        for m in files:
            for f in m.get("features", set()):
                phase_feats[f] += 1
        if phase_feats:
            top_concepts = []
            for k, n in phase_feats.most_common(8):
                title = CONCEPT_TITLES.get(k, k.replace("_", " ").title())
                top_concepts.append(f"{title} ({n})")
            callout_paragraphs = [
                Paragraph(
                    "<b>Python concepts you'll meet in this phase</b>",
                    styles["body_left"],
                ),
                Paragraph(
                    "&bull; " + " &nbsp;&middot;&nbsp; ".join(top_concepts),
                    styles["doc"],
                ),
                Paragraph(
                    "Each is explained in Chapter 2 (the primer). The "
                    "number in parentheses is how many of this phase's "
                    "files use that concept.",
                    styles["doc"],
                ),
            ]
            story.append(callout_table(callout_paragraphs, doc_width))
            story.append(Spacer(1, 0.1 * inch))

        signals_note_done = [False]
        for step_num, m in enumerate(files, 1):
            rel = m["path"].relative_to(REPO_ROOT).as_posix()
            name = m["path"].name

            story.append(Paragraph(
                f"Step {chap_no}.{step_num} — Build "
                f"<code>{esc(rel)}</code>",
                styles["h1"],
            ))

            # Beginner-friendly "Save / depends on" header.
            instr_paras: list = []
            instr_paras.append(Paragraph(
                f"<b>What to do.</b> Create the file "
                f"<code>{esc(rel)}</code> in your project root and "
                f"paste in the code shown in this step. The file is "
                f"<b>{m['loc']}</b> line"
                f"{'s' if m['loc'] != 1 else ''} long; we walk through "
                f"it piece by piece below.",
                styles["doc"],
            ))
            deps = internal_deps_for(m)
            if deps:
                instr_paras.append(Paragraph(
                    f"<b>Depends on.</b> This file imports from internal "
                    f"modules built in earlier steps: "
                    f"<code>{esc(', '.join(deps))}</code>. If any of "
                    f"those imports fail, jump back to the step that "
                    f"introduced them.",
                    styles["doc"],
                ))
            else:
                instr_paras.append(Paragraph(
                    "<b>Depends on.</b> No internal imports — this file "
                    "is self-contained and only relies on the standard "
                    "library plus packages from "
                    "<code>requirements.txt</code>.",
                    styles["doc"],
                ))
            hint = FILE_HINTS.get(name)
            if hint:
                instr_paras.append(Paragraph(
                    f"<b>What this file is for.</b> {hint}",
                    styles["doc"],
                ))
            story.append(callout_table(instr_paras, doc_width))
            story.append(Spacer(1, 0.08 * inch))

            render_module(story, m, styles, doc_width, signals_note_done)

        # End-of-phase checkpoint
        cp = PHASE_CHECKPOINTS.get(phase_index)
        if cp:
            story.append(Spacer(1, 0.1 * inch))
            story.append(callout_table([
                Paragraph(cp, styles["body"]),
            ], doc_width))

        chap_no += 1
        story.append(PageBreak())

    # ---- Frontend chapter (templates + CSS) ----
    if templates:
        build_frontend_chapter(
            story, styles, doc_width, chap_no, templates, static_info,
        )
        chap_no += 1
        story.append(PageBreak())

    # ---- Final chapter: glossary + index ----
    story.append(Paragraph(
        f"Chapter {chap_no} — Glossary &amp; concept index",
        styles["chapter"],
    ))
    story.append(Paragraph(
        "Two reference tools. The glossary defines terms specific to this "
        "codebase — the trading domain it lives in, plus a few Python and "
        "framework names worth pinning down. The concept index maps every "
        "Python feature detected by the AST scanner to the modules that "
        "actually use it, so you can jump straight from a concept to a "
        "concrete working example.",
        styles["body"],
    ))

    story.append(Paragraph("Glossary", styles["h1"]))
    glossary = [
        ("MT5 / MetaTrader 5",
         "The retail-trader desktop platform from MetaQuotes. Exposes "
         "a Python API (the <code>MetaTrader5</code> package) that this "
         "codebase uses for order placement and history retrieval."),
        ("Prop firm",
         "A proprietary trading firm that funds traders against an "
         "evaluation. Topstep, FundedNext, Tradovate, and TradeOpss are "
         "the four this codebase integrates with."),
        ("Funded account",
         "An account a prop firm has cleared the trader to trade real "
         "capital on, after passing the evaluation challenge."),
        ("Hedging",
         "Holding offsetting positions across linked accounts so that "
         "drawdown on one is bounded by gains on the other. The "
         "hedge_protector module implements this."),
        ("Watermark / high-water mark",
         "The peak equity an account has reached. Payouts are calculated "
         "on profit above this watermark to prevent paying twice on the "
         "same gain."),
        ("Phase",
         "An account's evaluation stage: challenge, verification, or "
         "funded. phase_manager.py owns the state machine."),
        ("Flask",
         "Python micro-web-framework powering the dashboard. Routes are "
         "registered with the <code>@app.route</code> decorator."),
        ("SQLAlchemy",
         "Python ORM. Database tables are declared as Python classes "
         "under dashboard/models.py."),
        ("Alembic",
         "Migration framework that pairs with SQLAlchemy. Each file in "
         "alembic/versions/ is a forward + rollback step."),
        ("APScheduler",
         "Cron-style job scheduler used by dashboard/scheduler.py to "
         "run periodic resyncs."),
        ("Selenium / CDP",
         "Browser-automation tooling. The prop-firm scrapers either "
         "drive a Chrome instance via Selenium or attach via the Chrome "
         "DevTools Protocol to read network traffic."),
        ("Tkinter",
         "The standard-library GUI toolkit Python ships with. The "
         "trader companion's desktop window is built with it."),
        ("Gunicorn",
         "Production WSGI server. Loads wsgi.py and runs the Flask app "
         "behind a worker pool."),
    ]
    for term, definition in glossary:
        story.append(Paragraph(f"<b>{esc(term)}</b>", styles["body_left"]))
        story.append(Paragraph(definition, styles["doc"]))

    # Concept index
    story.append(Paragraph("Concept index", styles["h1"]))
    story.append(Paragraph(
        "Each Python language feature, with the modules that use it. "
        "Concepts that appear in many modules are listed first; rarer "
        "ones at the end.",
        styles["body"],
    ))

    by_concept: dict[str, list[str]] = defaultdict(list)
    for m in modules:
        rel = m["path"].relative_to(REPO_ROOT).as_posix()
        for f in m["features"]:
            by_concept[f].append(rel)

    sorted_concepts = sorted(
        by_concept.items(), key=lambda kv: (-len(kv[1]), kv[0]),
    )
    for key, paths in sorted_concepts:
        title = CONCEPT_TITLES.get(key, key.replace("_", " ").title())
        story.append(Paragraph(
            f"<b>{esc(title)}</b> &nbsp;<font color='#a0aec0'>"
            f"({len(paths)} module{'s' if len(paths) != 1 else ''})</font>",
            styles["body_left"],
        ))
        sample = paths[:18]
        more = ""
        if len(paths) > 18:
            more = f" ... and {len(paths) - 18} more"
        story.append(Paragraph(
            esc(", ".join(sample)) + more, styles["doc"],
        ))

    return story


def main():
    files = collect_files()
    print(f"Scanning {len(files)} production files...")
    modules = []
    for i, f in enumerate(files, 1):
        try:
            modules.append(extract_module(f))
        except Exception as e:
            print(f"  [skip] {f.relative_to(REPO_ROOT)}: {e}")
        if i % 20 == 0:
            print(f"  parsed {i}/{len(files)}")

    template_paths = collect_templates()
    print(f"Scanning {len(template_paths)} HTML templates...")
    templates: list[dict] = []
    for p in template_paths:
        try:
            templates.append(extract_template(p))
        except Exception as e:
            print(f"  [skip template] {p.relative_to(REPO_ROOT)}: {e}")
    static_info = collect_static_assets()

    out = REPO_ROOT / "CODEBASE_REFERENCE.pdf"
    doc = BaseDocTemplate(
        str(out), pagesize=LETTER,
        leftMargin=0.85 * inch, rightMargin=0.85 * inch,
        topMargin=0.85 * inch, bottomMargin=0.7 * inch,
        title="MT5HedgingEngine — Reading Python Through a Real Codebase",
        author="Claude Code",
    )
    frame = Frame(
        doc.leftMargin, doc.bottomMargin, doc.width, doc.height, id="main",
    )
    doc.addPageTemplates([PageTemplate(id="all", frames=[frame], onPage=on_page)])

    styles = make_styles()
    story = build_story(
        modules, styles, doc.width,
        templates=templates, static_info=static_info,
    )
    print(f"Building PDF with {len(story)} flowables...")
    doc.build(story)
    size = out.stat().st_size / (1024 * 1024)
    print(f"Wrote {out} ({size:.1f} MB)")


if __name__ == "__main__":
    main()
