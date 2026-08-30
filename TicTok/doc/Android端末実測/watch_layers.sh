# 端末側で回すlayer監視。 sh /sdcard/watch_layers.sh [full]
# 既定は --list のみ(録画に無害)。full を渡すと変化時に全体dumpも撃つ(録画を約5-7 frame落とす)。
# 停止: adb shell rm /sdcard/gfx/RUN
OUT=/sdcard/gfx
MODE=$1
mkdir -p $OUT
touch $OUT/RUN
date +%s%N > $OUT/t_start.txt
dumpsys SurfaceFlinger --list > $OUT/base.txt
while [ -f $OUT/RUN ]; do
  dumpsys SurfaceFlinger --list > $OUT/cur.txt
  if ! cmp -s $OUT/cur.txt $OUT/base.txt; then
    ts=$(date +%s%N)
    diff $OUT/base.txt $OUT/cur.txt > $OUT/chg_$ts.txt 2>/dev/null
    if [ "$MODE" = "full" ]; then dumpsys SurfaceFlinger > $OUT/full_$ts.txt; fi
    cp $OUT/cur.txt $OUT/base.txt
  fi
  sleep 0.2
done
