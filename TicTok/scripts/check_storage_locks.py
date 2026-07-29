"""Storage の lock 契約を静的に検査する。

Storage は method 群を tictok/store/ の mixin へ分けているが、lock と DB 接続は
Storage が1組だけ持つ。そのため method 同士は「lock を保持したまま呼ぶ / 呼ばない」と
いう契約で結合しており、これを破ると deadlock か書き込みの atomicity 喪失になる。
どちらも test に出ない壊れ方(deadlock は負荷と timing 次第、atomicity 喪失は障害時
だけ)なので、code から機械的に見る手段をここに置く。

検査する事:
  1. lock の取得順が `_lock -> _buf_lock` の一方向だけであること。逆順が1つでも
     現れたら deadlock を新設したことになる。
  2. 名前が `_locked` で終わる method が、`self._lock` を保持しない場所から呼ばれて
     いないこと。呼び出し元が別 mixin にあっても追う。
  3. `_drain` の lock 区間の中で INSERT〜commit が完結していること(batch writer の
     commit 境界)。

使い方:
    venv/Scripts/python.exe scripts/check_storage_locks.py
終了コードは違反があれば 1。
"""
import ast
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
TARGETS = [ROOT / "tictok" / "storage.py"] + sorted((ROOT / "tictok" / "store").glob("*.py"))

# Storage が持つ lock。with self.<name>: を lock 取得とみなす。
LOCKS = ("_lock", "_buf_lock", "_read_lock", "_journal_lock", "_ops_fail_lock",
         "_read_init_lock", "_flush_cond")
# 許される取得順(外側, 内側)。ここに無い入れ子は違反として報告する。
ALLOWED_ORDER = {("_lock", "_buf_lock")}
WRITE_LOCK = "_lock"
# `_locked` 接尾辞が指す lock。既定は書き込み接続の _lock で、journal の file handle を
# 守る一群だけが別 lock を指す(DB接続には触れないため _lock とは独立)。
LOCK_OF = {"_journal_handle_locked": "_journal_lock"}


def _lock_name(item: ast.withitem):
    value = item.context_expr
    if (isinstance(value, ast.Attribute) and isinstance(value.value, ast.Name)
            and value.value.id == "self" and value.attr in LOCKS):
        return value.attr
    return None


class _Walker(ast.NodeVisitor):
    def __init__(self, owner: str, module: str) -> None:
        self.owner = owner
        self.module = module
        self.held: list = []
        self.calls: list = []
        self.orders: set = set()

    def visit_With(self, node: ast.With) -> None:
        acquired = [n for n in (_lock_name(i) for i in node.items) if n]
        for name in acquired:
            for outer in self.held:
                self.orders.add((outer, name, self.module, self.owner, node.lineno))
            self.held.append(name)
        for item in node.items:
            self.visit(item.context_expr)
        for statement in node.body:
            self.visit(statement)
        for _ in acquired:
            self.held.pop()

    visit_AsyncWith = visit_With

    def visit_Call(self, node: ast.Call) -> None:
        func = node.func
        if (isinstance(func, ast.Attribute) and isinstance(func.value, ast.Name)
                and func.value.id == "self"):
            self.calls.append((func.attr, tuple(self.held), self.module, self.owner, node.lineno))
        self.generic_visit(node)


def collect() -> tuple:
    methods: dict = {}
    orders: set = set()
    calls: list = []
    for path in TARGETS:
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for cls in tree.body:
            if not isinstance(cls, ast.ClassDef):
                continue
            if not (cls.name.endswith("Mixin") or cls.name == "Storage"):
                continue
            for item in cls.body:
                if not isinstance(item, (ast.FunctionDef, ast.AsyncFunctionDef)):
                    continue
                methods[item.name] = (path.name, item)
                walker = _Walker(item.name, path.name)
                for statement in item.body:
                    walker.visit(statement)
                orders |= walker.orders
                calls.extend(walker.calls)
    return methods, orders, calls


def reaches_under_lock(name: str, lock: str, methods: dict, calls: list, seen=None) -> bool:
    """name が、直接 or 間接に self.<lock> 保持下でだけ呼ばれているか。"""
    seen = seen or set()
    if name in seen:
        return True
    seen.add(name)
    sites = [c for c in calls if c[0] == name]
    if not sites:
        return False
    for _callee, held, _module, caller, _line in sites:
        if lock in held:
            continue
        if caller in methods and reaches_under_lock(caller, lock, methods, calls, seen):
            continue
        return False
    return True


def main() -> int:
    methods, orders, calls = collect()
    violations = []

    print(f"検査対象: {len(TARGETS)} file / {len(methods)} method")

    print("\n[1] lock の取得順 (外側 -> 内側)")
    observed = {(o, i) for o, i, *_ in orders}
    for outer, inner in sorted(observed):
        mark = "OK" if (outer, inner) in ALLOWED_ORDER else "違反"
        print(f"  {mark}  {outer} -> {inner}")
        if (outer, inner) not in ALLOWED_ORDER:
            for o, i, module, owner, line in sorted(orders):
                if (o, i) == (outer, inner):
                    violations.append(f"想定外の取得順 {o} -> {i} ({module}:{owner}:{line})")
    for outer, inner in sorted(ALLOWED_ORDER - observed):
        print(f"  --  {outer} -> {inner} (この版では出現せず)")

    print("\n[2] `_locked` method の呼び出し元")
    for name in sorted(n for n in methods if n.endswith("_locked")):
        module, _ = methods[name]
        lock = LOCK_OF.get(name, WRITE_LOCK)
        sites = [c for c in calls if c[0] == name]
        if not sites:
            print(f"  ??  {name} ({module}) 呼び出し元なし")
            violations.append(f"{name} に呼び出し元が無い")
            continue
        for _callee, held, call_module, caller, line in sites:
            if lock in held:
                verdict = "OK"
            elif reaches_under_lock(caller, lock, methods, calls):
                verdict = "OK(間接)"
            else:
                verdict = "違反"
                violations.append(
                    f"{name} が self.{lock} 区間の外から呼ばれている"
                    f" ({call_module}:{caller}:{line})")
            print(f"  {verdict:8s} {name} <- {call_module}:{caller}:{line}"
                  f" 要={lock} held={list(held)}")

    print("\n[3] _drain の commit 境界")
    _, drain = methods["_drain"]
    body = [n for n in drain.body
            if not (isinstance(n, ast.Expr) and isinstance(n.value, ast.Constant)
                    and isinstance(n.value.value, str))]
    if not (len(body) == 1 and isinstance(body[0], ast.With)
            and [_lock_name(i) for i in body[0].items] == [WRITE_LOCK]):
        violations.append("_drain 全体が単一の with self._lock: 区間に収まっていない")
        print("  違反 _drain の本体が with self._lock: 一本になっていない")
    else:
        commits = [n.lineno for n in ast.walk(drain)
                   if isinstance(n, ast.Call) and isinstance(n.func, ast.Attribute)
                   and n.func.attr == "commit"]
        walker = _Walker("_drain", "storage")
        for statement in drain.body:
            walker.visit(statement)
        outside = [c for c in walker.calls if c[0] == "_write_batch_locked" and WRITE_LOCK not in c[1]]
        print(f"  OK   _drain の本体は単一の with self._lock: 区間 "
              f"(commit {len(commits)} 箇所はすべてその内側)")
        if outside:
            violations.append("_write_batch_locked が _drain の lock 区間外にある")

    print()
    if violations:
        print(f"違反 {len(violations)} 件:")
        for v in violations:
            print("  -", v)
        return 1
    print("違反なし。")
    return 0


if __name__ == "__main__":
    sys.exit(main())
