"""model 呼び出しの薄い層。

中身は ..\\vfi\\rifelib.py の Rife(TensorRT)そのまま。別 Agent の
vfimodels.py / runner.py が出来たら、この file だけ差し替えれば済むようにする。

既定を v4.6 にした理由: 前回の検証で 5.32ms(188 fps)と最速級で、品質は
最良の v4.25_lite と LPIPS で 0.0162 対 0.0153(会話場面)しか違わない。
時刻の張り直しは model 呼び出し回数を桁で増やすので、速い側を選ぶ。
"""
import lib          # noqa: F401  (sys.path へ ../vfi を通すために先に import する)

DEFAULT = "v4.6"


class Model:
    def __init__(self, name=DEFAULT, w=lib.W, h=lib.H):
        import rifelib as R
        self._R = R
        self.name = name
        self.m = R.Rife(name, w, h, fp16=True)

    def infer(self, f0, f1, tau):
        """uint8 BGR HWC の cuda tensor 2枚 + tau -> uint8 BGR HWC の cuda tensor。

        返り値は次の infer で上書きされる view。持ち越すなら clone すること。
        """
        self._R.pack(f0, f1, tau, self.m.dtype, out=self.m.dev_in)
        return self._R.unpack(self.m.infer())

    def to_gpu(self, arr):
        return self._R.to_gpu(arr)
