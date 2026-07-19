"""静的file配信のCache-Control方針。

このtoolはlocalhost常駐の単一user向けで、CDNもreverse proxyも多段cacheも間に無い。
loopbackでは再送costがほぼ無い一方、JSとHTMLの版がズレると「直っている不具合が
直っていないように見える / 壊れているものが見えない」という検証事故になる。
そのため text資産は転送量よりも版の一致を優先し、常にrevalidateさせる。
大きいbinary資産(録画mp4・thumbnail・avatar)だけは再送costが実際に効くので、
各route側で明示的にmax-ageを付けている(ここは対象外)。

Cache-Controlを一切返さないとbrowserはLast-Modifiedからheuristicにcache期間を
推測する(RFC 9111 4.2.2)。これが版ズレの原因なので、静的fileには必ず明示する。

方針の分類:
    document / app asset  : ``no-cache`` = cacheはするが毎回revalidate。
                            変更が無ければETagで304になり再送は発生しない。
    vendor asset          : 滅多に更新されないため期限付きでrevalidateも省く。
                            ``immutable`` にすると差し替え時に手動でcache破棄が
                            必要になるので、期限付きに留めて自然に追従させる。
"""
from pathlib import PurePosixPath

# 毎回revalidateさせる指定。stale-while-revalidate等は付けない(古い版を一瞬でも
# 表示させないため)。
REVALIDATE_CACHE_CONTROL = "no-cache"

# vendor同梱libraryをrevalidate無しで再利用してよい期間。差し替えてもこの期間内に
# 自然へ追従する長さとして1日。
VENDOR_ASSET_MAX_AGE_SECONDS = 86400
VENDOR_ASSET_CACHE_CONTROL = f"public, max-age={VENDOR_ASSET_MAX_AGE_SECONDS}"

# static配下でvendor扱いにするdirectory名。
VENDOR_DIRNAME = "vendor"


def static_cache_control(relative_path) -> str:
    """static root からの相対pathに対して返すべきCache-Controlを決める。"""
    parts = PurePosixPath(str(relative_path).replace("\\", "/")).parts
    if VENDOR_DIRNAME in parts:
        return VENDOR_ASSET_CACHE_CONTROL
    return REVALIDATE_CACHE_CONTROL
