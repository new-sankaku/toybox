# -*- coding: utf-8 -*-
"""
【手元のターミナルで動かす】ダブルクリックでは窓がすぐ閉じて何も見えません。
Resolveで動かす/10_実務_字幕を装飾する.py を Resolve の Workspace > Scripts メニューに出す。
Resolve が起動時に読む Fusion/Scripts/Utility へ、装飾データ.json と対で複製するだけ。

    python 手元で動かす/導入_Resolveのメニューへ登録.py

複製なので、装飾を変えて 手元で動かす/道具_装飾プリセットを生成.py を実行し直したら、これも実行し直す。
Resolve を起動したままだと反映されないので、Resolve を再起動する。

Resolve の scripting は無料版でも使える。Studio 限定なのは AI 系など一部の機能だけで、
ここで使う API はすべて共通（Developer/Scripting/README.txt の
"Studio and AI Scripting APIs" に「Free と Studio 共通の superset」と書かれている）。
"""

import io
import os
import sys

# 10_実務_字幕を装飾する.py は装飾の表を持たず、隣に置いた 装飾データ.json を読む。
# 片方だけ古いと、script は黙って古い装飾を当てる。必ず対で複製する。
COPIES = [os.path.join("Resolveで動かす", "10_実務_字幕を装飾する.py"), "装飾データ.json"]

# 以前このプロジェクトが置いていた名前。まとめる前・番号を付ける前のものが残っていると
# メニューに古い script が並ぶので、見つけたら消す。
RETIRED = ["装飾を切り替える.py", "字幕をText+に置き換える.py", "Text+の装飾を一括変更.py",
           "見本を書き出す.py", "全部の装飾を並べる.py", "装飾ツール.py",
           "4_装飾ツール.py", "6_別の見せ方を組む.py",
           "5_別の見せ方を組む.py",
           "3_装飾ツール.py",
           "実務_字幕を装飾する.py",
           "実務_字幕へ目印を付ける.py"]   # 番号を付ける前の名前

# Resolve が起動時に読むフォルダ（Developer/Scripting/README.txt に記載のうち利用者ごとの場所）
FOLDERS = {
    "win32": r"%APPDATA%\Blackmagic Design\DaVinci Resolve\Support\Fusion\Scripts\Utility",
    "darwin": "~/Library/Application Support/Blackmagic Design/DaVinci Resolve/Fusion/Scripts/Utility",
    "linux": "~/.local/share/DaVinciResolve/Fusion/Scripts/Utility",
}


def target_folder():
    """このOSでの置き場所を返す。"""
    key = "linux" if sys.platform.startswith("linux") else sys.platform
    raw = FOLDERS.get(key)
    if raw is None:
        return None
    return os.path.expanduser(os.path.expandvars(raw))


def main():
    folder = target_folder()
    if folder is None:
        print("このOS（%s）の置き場所が分かりません。" % sys.platform)
        return
    if not os.path.isdir(folder):
        print("Resolve のスクリプト置き場がありません: %s" % folder)
        print("DaVinci Resolve を一度起動すると作られます。")
        return

    # この script は 手元で動かす/ に居る。複製するものは1つ上の階層にある。
    here = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    # 片方だけ新しくならないよう、1つでも欠けていたら何も置かずに止める。
    lack = [name for name in COPIES if not os.path.isfile(os.path.join(here, name))]
    if lack:
        print("%s がありません。" % "・".join(lack))
        print("手元で動かす/道具_装飾プリセットを生成.py を実行すると 装飾データ.json が作られます。")
        return

    for name in COPIES:
        source = os.path.join(here, name)
        with io.open(source, encoding="utf-8") as handle:
            body = handle.read()
        destination = os.path.join(folder, os.path.basename(name))
        with io.open(destination, "w", encoding="utf-8", newline="\n") as handle:
            handle.write(body)
        print("置きました: %s" % destination)

    for name in RETIRED:
        stale = os.path.join(folder, name)
        if os.path.isfile(stale):
            os.remove(stale)
            print("古い script を消しました: %s" % stale)

    print("DaVinci Resolve を再起動すると Workspace > Scripts に出ます。")


main()
