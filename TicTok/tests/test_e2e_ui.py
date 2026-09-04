"""画面のE2E smoke。実serverを起こし、headless Chromiumで主要画面を開く。

**隔離が最優先**: 起動したserverは外部世界(TikTok接続・録画fileの書き込み)へ副作用を
持つ。本番資産へ触れないために、この module は必ず

  1. 空のDB(本番DBのcopyではない)      → 監視対象0・中断録画0で回収も接続も走らない
  2. tmp配下の record / log / journal   → 空DBならsettings表も空なのでenvがそのまま効く
  3. TICTOK_NO_RESTORE=1                → 監視対象の復元を止める(config.get_no_restore)
  4. 空きportへの割り当て               → userのserverと同時に動かせる
                                          (instance lockは <db path>.lock なので衝突しない)

を満たす。本番DBをcopyして起動する形にはしない — settings表の record_dir が
env より優先されるため、copy DBは本番の録画folderを掴む。
"""
import os
import re
import socket
import subprocess
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

import pytest

from tictok.paths import PROJECT_ROOT

pytestmark = pytest.mark.slow

# nav (static/common.js の NAV_ITEMS) と同じ順序・同じ14画面。
# nav の文言と <title> は別物なので混ぜない(/streamers は nav「配信者」/ title「配信者分析」)。
PAGES = [
    ("/", "index.html"),
    ("/overview", "overview.html"),
    ("/history", "history.html"),
    ("/streamers", "streamers.html"),
    ("/videos", "videos.html"),
    ("/story", "story.html"),
    ("/capacity", "capacity.html"),
    ("/fans", "fans.html"),
    ("/analytics", "analytics.html"),
    ("/jobs", "jobs.html"),
    ("/assets", "assets.html"),
    ("/ops", "ops.html"),
    ("/backup", "backup.html"),
    ("/settings", "settings.html"),
]


def _title_of(html_name: str) -> str:
    """static/<html_name> が名乗る <title>。

    期待値をtestへ書き写すと、画面名を変えたときにtestだけ古くなる。route が
    「その画面のHTML」を返しているかを見たいので、file 自身のtitleを正とする。
    """
    text = (PROJECT_ROOT / "static" / html_name).read_text(encoding="utf-8")
    match = re.search(r"<title>(.*?)</title>", text, re.S)
    assert match, f"{html_name} に <title> がありません"
    return match.group(1).strip()

# server が応答を返せるようになったかを見る read-only route。
READY_PATH = "/api/monitors"
BOOT_TIMEOUT_SECONDS = 120


def _free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return int(s.getsockname()[1])


async def _require_browser(driver):
    """Chromium の実体が無い環境ではE2Eを飛ばす。"""
    exe = driver.chromium.executable_path
    if not exe or not Path(exe).exists():
        pytest.skip("Chromium が未installです (python -m playwright install chromium)")


def _sandbox_env(sandbox: Path, port: int) -> dict:
    env = {k: v for k, v in os.environ.items() if not k.startswith("TICTOK_")}
    env.update(
        {
            "TICTOK_DB_PATH": str(sandbox / "tictok.db"),
            "TICTOK_RECORD_DIR": str(sandbox / "recordings"),
            "TICTOK_RECORD_DIR_FINAL": str(sandbox / "recordings"),
            "TICTOK_LOG_DIR": str(sandbox / "logs"),
            "TICTOK_JOURNAL_DIR": str(sandbox / "journal"),
            "TICTOK_SAMPLE_DIR": str(sandbox / "samples"),
            "TICTOK_HOST": "127.0.0.1",
            "TICTOK_PORT": str(port),
            # 実配信への接続・監視復元を止める。
            "TICTOK_NO_RESTORE": "1",
            "TICTOK_SIMULATION": "0",
            "TICTOK_EULER_API_KEY": "",
            # 重いmodelの読み込みを起動path から外す(画面の描画確認には要らない)。
            "TICTOK_AI_ENABLED": "0",
            "TICTOK_STT_ENABLED": "0",
            "TICTOK_SEMANTIC_ENABLED": "0",
            "TICTOK_UPSCALE_ENABLED": "0",
        }
    )
    return env


@pytest.fixture(scope="session")
def ui_server(tmp_path_factory):
    """隔離serverを起こし、base URL を返す。

    subprocess と urllib だけで書く(asyncio を持ち込まない)。ここが session を跨いで
    生きるfixtureなので、event loop に触れる物を置くと後続の全testを巻き込む。
    """
    pytest.importorskip("playwright.async_api", reason="playwright が入っていません")
    sandbox = tmp_path_factory.mktemp("e2e")
    for name in ("recordings", "logs", "journal", "samples"):
        (sandbox / name).mkdir(parents=True, exist_ok=True)
    port = _free_port()

    # stdout を pipe にすると log で buffer が埋まり server が止まる。file へ落とす。
    log_path = sandbox / "server.stdout.log"
    with open(log_path, "w", encoding="utf-8", errors="replace") as out:
        proc = subprocess.Popen(
            [sys.executable, "main.py"],
            cwd=str(PROJECT_ROOT),
            env=_sandbox_env(sandbox, port),
            stdout=out,
            stderr=subprocess.STDOUT,
        )
        base = f"http://127.0.0.1:{port}"
        try:
            deadline = time.monotonic() + BOOT_TIMEOUT_SECONDS
            while time.monotonic() < deadline:
                if proc.poll() is not None:
                    tail = log_path.read_text("utf-8", errors="replace")[-4000:]
                    pytest.fail(f"serverが起動直後に終了しました:\n{tail}")
                try:
                    with urllib.request.urlopen(base + READY_PATH, timeout=2) as res:
                        if res.status == 200:
                            break
                except (urllib.error.URLError, OSError, TimeoutError):
                    time.sleep(0.5)
            else:
                tail = log_path.read_text("utf-8", errors="replace")[-4000:]
                pytest.fail(f"serverが{BOOT_TIMEOUT_SECONDS}秒で応答しませんでした:\n{tail}")

            # 起動したserverが本当にsandboxを掴んでいるか確かめてから使う。
            # (settings表の record_dir が env より優先されるため、ここを確かめずに
            #  進めると本番の録画folderを見ているserverでtestすることになる)
            strays = list((sandbox / "recordings").rglob("*.ts"))
            assert strays == [], f"起動だけでsandboxへ録画が現れました: {strays}"
            yield base
        finally:
            proc.terminate()
            try:
                proc.wait(timeout=20)
            except subprocess.TimeoutExpired:
                proc.kill()
                proc.wait(timeout=10)

    # 隔離が効いていたことの事後確認。実配信へ繋いでいれば録画fileが落ちている。
    assert list((sandbox / "recordings").rglob("*.ts")) == []
    assert list((sandbox / "recordings").rglob("*.mp4")) == []


# playwright は **async API** を使う。sync API は driver を greenlet 上の専用 event loop で
# 回すため、`sync_playwright()` が開いている間ずっと **その thread の running loop が
# 設定されたまま**になる(実測: `asyncio._get_running_loop()` が生きた loop を返し、
# `asyncio.run()` が "cannot be called from a running event loop" で落ちる)。
# これを session scope の fixture で開くと、その後この session で走る async test が
# 全部巻き添えになる。async API なら pytest-asyncio と同じ loop に乗るのでこの問題自体が無い。
#
# その代わり、async fixture の loop scope は pytest.ini の
# `asyncio_default_fixture_loop_scope = function` に従う。browser を session scope に
# すると loop scope が食い違うため、test ごとに Chromium を起こす。
# 起動は 1 秒未満で、server(session scope・asyncio 非依存)は使い回すので実害は小さい。
@pytest.fixture
async def browser():
    from playwright.async_api import async_playwright

    async with async_playwright() as driver:
        await _require_browser(driver)
        instance = await driver.chromium.launch()
        try:
            yield instance
        finally:
            await instance.close()


@pytest.fixture
async def page(browser):
    """console error と未捕捉例外を集めるpage。"""
    context = await browser.new_context(viewport={"width": 1600, "height": 1000})
    page = await context.new_page()
    page.js_errors = []
    page.on("pageerror", lambda err: page.js_errors.append(f"pageerror: {err}"))
    page.on(
        "console",
        lambda msg: page.js_errors.append(f"console.error: {msg.text}")
        if msg.type == "error"
        else None,
    )
    try:
        yield page
    finally:
        await context.close()


@pytest.mark.parametrize("path,html", PAGES, ids=[p.strip("/") or "index" for p, _ in PAGES])
async def test_page_renders_without_js_error(ui_server, page, path, html):
    """13画面がJS errorなしで描画され、navが全画面ぶん出る。"""
    await page.goto(ui_server + path, wait_until="networkidle")
    # route が別画面のHTMLを返していないこと。
    assert (await page.title()) == _title_of(html)

    links = await page.eval_on_selector_all(
        "nav.a-nav a", "els => els.map(e => [e.getAttribute('href'), e.textContent])"
    )
    assert len(links) == len(PAGES)
    assert [href for href, _ in links] == [p for p, _ in PAGES]

    # 現在地だけがactive。
    active = await page.eval_on_selector_all(
        "nav.a-nav a.active", "els => els.map(e => e.getAttribute('href'))"
    )
    assert active == [path]

    assert page.js_errors == []


async def test_websocket_connects(ui_server, page):
    """WSが繋がると全画面のtopbarがONLINEを名乗る。"""
    await page.goto(ui_server + "/", wait_until="networkidle")
    await page.wait_for_function(
        "() => document.querySelector('#ws-status')"
        "&& document.querySelector('#ws-status').textContent.includes('ONLINE')",
        timeout=15000,
    )
    assert page.js_errors == []


async def test_nav_moves_between_pages(ui_server, page):
    """navのlinkで実際に画面を移れる(routeが登録されていないpageを見逃さない)。"""
    await page.goto(ui_server + "/", wait_until="networkidle")
    for path, html in PAGES[1:]:
        await page.click(f"nav.a-nav a[href='{path}']")
        await page.wait_for_load_state("networkidle")
        assert page.url.endswith(path)
        assert (await page.title()) == _title_of(html)
    assert page.js_errors == []


async def test_jump_overlay_opens_and_closes(ui_server, page):
    """Ctrl+K の横断jumpが開き、候補の取得まで進む。"""
    await page.goto(ui_server + "/", wait_until="networkidle")
    assert (await page.query_selector(".jump-overlay")) is None

    await page.keyboard.press("Control+k")
    await page.wait_for_selector(".jump-overlay:not(.hidden)", timeout=10000)
    # 空DBなので候補は0件。0件と取得失敗は描き分けられている必要がある
    # (「読み込み中…」で止まったままでもない)。
    await page.wait_for_function(
        "() => { const n = document.querySelector('.jump-note');"
        " return n && n.textContent.trim() && !n.textContent.includes('読み込み中'); }",
        timeout=10000,
    )
    note = await page.text_content(".jump-note")
    assert "取得できませんでした" not in note, note
    assert "検索対象:" in note, note

    await page.keyboard.press("Escape")
    await page.wait_for_selector(".jump-overlay", state="hidden", timeout=5000)
    assert page.js_errors == []


async def test_videos_tabs_switch(ui_server, page):
    """配信者動画のtabが切り替わる(view の出し分けが効いている)。"""
    await page.goto(ui_server + "/videos", wait_until="networkidle")
    # 文字起こしは一括処理の1種別になり、専用tabは無くなった(選ぶ場所と進捗を見る場所が
    # 別tabに固定され、1回の作業で必ず往復していたため)。切り出しリストも見どころへ
    # 畳んだ(同じ範囲を2つの表で持っていた)。
    for view in ["marks", "groups", "bulk", "search"]:
        await page.click(f"#tab-{view}")
        await page.wait_for_selector(f"#view-{view}:not(.hidden)", timeout=5000)
        classes = (await page.get_attribute(f"#tab-{view}", "class")).split()
        assert classes.count("active") == 1
    assert page.js_errors == []


async def test_job_kind_filter_is_built_from_the_server(ui_server, page):
    """Job画面の種別選択肢がserverの応答から生える。

    labelの出所は core/ops_labels.py だけで、画面は受け取って引く。応答が届かない・key名が
    変わったといった食い違いは、jsdomのstubでは stub を直せば通ってしまうため、実serverを
    叩くここで見る(壊れると『全て』しか選べない種別filterになる)。"""
    await page.goto(ui_server + "/jobs", wait_until="networkidle")
    await page.wait_for_function(
        "() => document.querySelectorAll('#job-flt-kind option').length > 1", timeout=15000,
    )
    values = await page.eval_on_selector_all(
        "#job-flt-kind option", "els => els.map(e => e.value)")
    assert values[0] == "all"
    for domain in ["overlay", "upscale", "stt", "session_overlay", "bulk_overlay"]:
        assert domain in values
    labels = await page.eval_on_selector_all(
        "#job-flt-kind option", "els => els.map(e => e.textContent)")
    assert "Up出力" in labels
    assert page.js_errors == []


async def test_job_column_sort_reorders_and_returns_to_default(ui_server, page):
    """列headerのclickで並べ替えが効き、3回目で既定へ戻る。"""
    await page.goto(ui_server + "/jobs", wait_until="networkidle")
    head = "#job-table th[data-sort='queued']"
    await page.click(head)
    assert (await page.get_attribute(head, "aria-sort")) == "descending"
    await page.click(head)
    assert (await page.get_attribute(head, "aria-sort")) == "ascending"
    await page.click(head)
    assert (await page.get_attribute(head, "aria-sort")) == "none"
    assert page.js_errors == []


async def test_empty_db_pages_say_zero_not_failure(ui_server, page):
    """空DBの一覧が「取得失敗」を出さない(0件と失敗の描き分け)。"""
    for path in ["/history", "/streamers", "/fans", "/jobs", "/ops"]:
        await page.goto(ui_server + path, wait_until="networkidle")
        await page.wait_for_timeout(500)
        failed = await page.eval_on_selector_all(
            ".list-failed", "els => els.map(e => e.textContent)"
        )
        assert failed == [], f"{path}: {failed}"
    assert page.js_errors == []
