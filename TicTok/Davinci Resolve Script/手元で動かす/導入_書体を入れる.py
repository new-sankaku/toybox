# -*- coding: utf-8 -*-
"""
【手元のターミナルで動かす】ダブルクリックでは窓がすぐ閉じて何も見えません。
fonts/ の書体を、ログインしているユーザーだけに入れる。管理者権限は要らない。

    python 手元で動かす/導入_書体を入れる.py           入れる
    python 手元で動かす/導入_書体を入れる.py --remove  外す
    python 手元で動かす/導入_書体を入れる.py --list    今の状態を見る

Windows は %LOCALAPPDATA%\\Microsoft\\Windows\\Fonts に置いて
HKCU の Fonts に名前を登録する。Linux は ~/.local/share/fonts に置いて fc-cache を回す。
どちらも入れたものだけを消すので、元から入っていた書体には触らない。

Resolve は起動時にしか書体を読み直さないため、入れたあとに Resolve を再起動する。
"""

import os
import shutil
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)   # 手元で動かす/ の1つ上（ふだん使うものが並ぶ場所）
FONT_DIR = os.path.join(ROOT, "fonts")
REG_KEY = r"Software\Microsoft\Windows NT\CurrentVersion\Fonts"


def font_files():
    if not os.path.isdir(FONT_DIR):
        raise SystemExit("fonts フォルダがありません: %s" % FONT_DIR)
    names = sorted(n for n in os.listdir(FONT_DIR)
                   if n.lower().endswith((".ttf", ".otf", ".ttc")))
    if not names:
        raise SystemExit("fonts フォルダに書体がありません。")
    return names


def user_font_dir():
    if sys.platform == "win32":
        return os.path.join(os.environ["LOCALAPPDATA"], "Microsoft", "Windows", "Fonts")
    return os.path.join(os.path.expanduser("~"), ".local", "share", "fonts")


def reg_name(name):
    """レジストリに載せる表示名。実際の書体名ではなくファイル名から作る。"""
    return os.path.splitext(name)[0] + (" (OpenType)" if name.lower().endswith(".otf")
                                        else " (TrueType)")


def win_reg(action, name, path=None):
    import winreg
    access = winreg.KEY_SET_VALUE if action != "read" else winreg.KEY_READ
    with winreg.CreateKeyEx(winreg.HKEY_CURRENT_USER, REG_KEY, 0, access) as key:
        if action == "set":
            winreg.SetValueEx(key, reg_name(name), 0, winreg.REG_SZ, path)
        elif action == "delete":
            try:
                winreg.DeleteValue(key, reg_name(name))
            except FileNotFoundError:
                pass
        else:
            try:
                return winreg.QueryValueEx(key, reg_name(name))[0]
            except FileNotFoundError:
                return None


def add_font_resource(path):
    """今動いているセッションにも即座に反映させる（再ログイン待ちを避ける）。"""
    import ctypes
    gdi = ctypes.WinDLL("gdi32")
    if gdi.AddFontResourceW(ctypes.c_wchar_p(path)) == 0:
        return False
    ctypes.WinDLL("user32").PostMessageW(0xFFFF, 0x001D, 0, 0)  # HWND_BROADCAST, WM_FONTCHANGE
    return True


def remove_font_resource(path):
    import ctypes
    ctypes.WinDLL("gdi32").RemoveFontResourceW(ctypes.c_wchar_p(path))
    ctypes.WinDLL("user32").PostMessageW(0xFFFF, 0x001D, 0, 0)


def install():
    target = user_font_dir()
    if not os.path.isdir(target):
        os.makedirs(target)
    done = []
    kept = []
    for name in font_files():
        src = os.path.join(FONT_DIR, name)
        dst = os.path.join(target, name)
        # すでに同じものが入っているなら触らない。使用中のファイルは上書きできず、
        # 1本でも失敗すると残り全部が入らなくなる。
        if os.path.isfile(dst) and os.path.getsize(dst) == os.path.getsize(src):
            kept.append(name)
            continue
        try:
            shutil.copyfile(src, dst)
        except (PermissionError, OSError) as trouble:
            print("%s は置き替えられません（使用中かもしれません）: %s" % (name, trouble))
            continue
        if sys.platform == "win32":
            win_reg("set", name, dst)
            if not add_font_resource(dst):
                print("%s を読み込めませんでした。" % name)
                continue
        done.append(name)
    if kept:
        print("すでに入っているもの: %s" % ", ".join(kept))
    if sys.platform != "win32":
        subprocess.call(["fc-cache", "-f", target])
    print("入れました: %s" % ", ".join(done))
    print("置き場所: %s" % target)
    print("Resolve を起動中なら、書体一覧に出すために再起動してください。")


def remove():
    target = user_font_dir()
    done = []
    for name in font_files():
        dst = os.path.join(target, name)
        if sys.platform == "win32":
            if os.path.isfile(dst):
                remove_font_resource(dst)
            win_reg("delete", name)
        if os.path.isfile(dst):
            os.remove(dst)
            done.append(name)
    if sys.platform != "win32":
        subprocess.call(["fc-cache", "-f", target])
    print("外しました: %s" % (", ".join(done) if done else "対象なし"))


def show():
    target = user_font_dir()
    for name in font_files():
        dst = os.path.join(target, name)
        state = "置いてある" if os.path.isfile(dst) else "置いていない"
        if sys.platform == "win32":
            state += " / レジストリ登録 " + ("あり" if win_reg("read", name) else "なし")
        print("%s: %s" % (name, state))


def main():
    arg = sys.argv[1] if len(sys.argv) > 1 else ""
    if arg == "--remove":
        remove()
    elif arg == "--list":
        show()
    elif arg in ("", "--install"):
        install()
    else:
        print(__doc__)


main()
