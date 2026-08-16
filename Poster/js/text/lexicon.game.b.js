(function (PF) {
'use strict';

// TODO: 各poolは目標件数に未達。agent の session limit 復帰後に追記する。
Object.assign(PF.GENRE_POOLS.game, {
  theme: [
    { ja: '覇', en: 'SUPREMACY' }, { ja: '蒼穹', en: 'FIRMAMENT' }, { ja: '焔', en: 'BLAZE' },
    { ja: '剣', en: 'BLADE' }, { ja: '神', en: 'DEITY' }, { ja: '竜', en: 'DRAGON' },
    { ja: '機', en: 'MACHINA' }, { ja: '銀河', en: 'GALAXY' }, { ja: '深淵', en: 'ABYSS' },
    { ja: '星霜', en: 'AEON' }, { ja: '刻', en: 'CHRONOS' }, { ja: '風', en: 'GALE' },
    { ja: '氷', en: 'GLACIER' }, { ja: '雷', en: 'THUNDER' }, { ja: '闇', en: 'UMBRA' },
    { ja: '光', en: 'LUMEN' }, { ja: '鋼', en: 'STEEL' }, { ja: '影', en: 'SHADE' },
    { ja: '砂海', en: 'SANDSEA' }, { ja: '樹海', en: 'GREATWOOD' }, { ja: '天空', en: 'SKYREALM' },
    { ja: '地底', en: 'UNDERDEEP' }, { ja: '極北', en: 'FARNORTH' }, { ja: '黄昏', en: 'TWILIGHT' },
    { ja: '暁', en: 'DAWNBREAK' }, { ja: '常世', en: 'ETERNAL' }, { ja: '幽世', en: 'OTHERSIDE' },
    { ja: '八咫', en: 'YATA' }, { ja: '玄武', en: 'GENBU' }, { ja: '朱雀', en: 'SUZAKU' },
    { ja: '白虎', en: 'BYAKKO' }, { ja: '青龍', en: 'SEIRYU' }, { ja: '麒麟', en: 'KIRIN' },
    { ja: '鵬', en: 'ROC' }, { ja: '獅子', en: 'LION' }, { ja: '狼', en: 'WOLF' },
    { ja: '鴉', en: 'RAVEN' }, { ja: '蛇', en: 'SERPENT' }, { ja: '鯨', en: 'LEVIATHAN' },
    { ja: '兜', en: 'HELM' }, { ja: '鎧', en: 'ARMOR' }, { ja: '弓', en: 'BOW' },
    { ja: '槍', en: 'LANCE' }, { ja: '斧', en: 'AXE' }, { ja: '盾', en: 'AEGIS' },
    { ja: '王冠', en: 'CROWN' }, { ja: '玉座', en: 'THRONE' }, { ja: '聖杯', en: 'GRAIL' },
    { ja: '魔導', en: 'ARCANE' }, { ja: '錬金', en: 'ALCHEMY' }, { ja: '呪印', en: 'SIGIL' },
    { ja: '契約', en: 'COVENANT' }, { ja: '封印', en: 'SEAL' }, { ja: '結界', en: 'WARD' },
    { ja: '塔', en: 'SPIRE' }, { ja: '城', en: 'CITADEL' }, { ja: '砦', en: 'BASTION' },
    { ja: '迷宮', en: 'LABYRINTH' }, { ja: '遺跡', en: 'RUINS' }, { ja: '祭壇', en: 'ALTAR' },
    { ja: '方舟', en: 'ARK' }, { ja: '歯車', en: 'COGWHEEL' }, { ja: '蒸気', en: 'STEAM' },
    { ja: '鉄路', en: 'IRONRAIL' }, { ja: '羅針', en: 'COMPASS' }, { ja: '星辰', en: 'ASTRAL' },
    { ja: '虚空', en: 'VOID' }, { ja: '次元', en: 'DIMENSION' }, { ja: '因果', en: 'CAUSALITY' },
    { ja: '輪廻', en: 'SAMSARA' }, { ja: '黎明', en: 'DAYSPRING' }, { ja: '終焉', en: 'ENDING' }
  ],
  nounTail: [
    { ja: '戦記', en: 'CHRONICLE' }, { ja: '叙事詩', en: 'SAGA' }, { ja: '覚醒', en: 'AWAKENING' },
    { ja: '討伐', en: 'SUBJUGATION' }, { ja: '継承者', en: 'INHERITOR' }, { ja: '大陸', en: 'CONTINENT' },
    { ja: '紀元', en: 'EPOCH' }, { ja: '決戦', en: 'DECISIVE BATTLE' }, { ja: '幻想曲', en: 'FANTASIA' },
    { ja: '兵団', en: 'LEGION' }, { ja: '遺産', en: 'LEGACY' }, { ja: '系統樹', en: 'PHYLOGENY' },
    { ja: '黙示録', en: 'APOCALYPSE' }, { ja: '英雄譚', en: 'HEROIC TALE' }, { ja: '放浪記', en: 'WANDERING' },
    { ja: '開拓史', en: 'PIONEER LOG' }, { ja: '建国記', en: 'FOUNDING' }, { ja: '航海誌', en: 'VOYAGE LOG' },
    { ja: '探検記', en: 'EXPEDITION' }, { ja: '調査録', en: 'SURVEY' }, { ja: '観測記', en: 'OBSERVATION' },
    { ja: '生存記', en: 'SURVIVAL' }, { ja: '再興', en: 'RESTORATION' }, { ja: '興亡', en: 'RISE AND FALL' },
    { ja: '転生', en: 'REBIRTH' }, { ja: '召喚', en: 'SUMMONING' }, { ja: '解放', en: 'LIBERATION' },
    { ja: '奪還', en: 'RECAPTURE' }, { ja: '防衛戦', en: 'DEFENSE' }, { ja: '包囲戦', en: 'SIEGE' },
    { ja: '争奪戦', en: 'SCRAMBLE' }, { ja: '選定', en: 'SELECTION' }, { ja: '審判', en: 'JUDGMENT' },
    { ja: '試練', en: 'TRIAL' }, { ja: '儀式', en: 'RITE' }, { ja: '祭', en: 'FESTIVAL' },
    { ja: '大戦', en: 'GREAT WAR' }, { ja: '終章', en: 'FINAL CHAPTER' }, { ja: '序章', en: 'PRELUDE' },
    { ja: '外伝', en: 'SIDE STORY' }, { ja: '前日譚', en: 'PREQUEL' }, { ja: '後日譚', en: 'EPILOGUE' }
  ],
  adj: [
    { ja: '果てなき', en: 'ETERNAL' }, { ja: '選ばれし', en: 'CHOSEN' }, { ja: '蒼き', en: 'AZURE' },
    { ja: '紅蓮の', en: 'CRIMSON' }, { ja: '極限の', en: 'EXTREME' }, { ja: '最果ての', en: 'FARTHEST' },
    { ja: '断ち切れぬ', en: 'UNBROKEN' }, { ja: '失われし', en: 'LOST' }, { ja: '忘れられし', en: 'FORGOTTEN' },
    { ja: '禁じられた', en: 'FORBIDDEN' }, { ja: '約束されし', en: 'PROMISED' }, { ja: '眠れる', en: 'SLUMBERING' },
    { ja: '荒ぶる', en: 'RAGING' }, { ja: '静寂の', en: 'SILENT' }, { ja: '黄金の', en: 'GOLDEN' },
    { ja: '銀嶺の', en: 'SILVER PEAK' }, { ja: '漆黒の', en: 'PITCH BLACK' }, { ja: '純白の', en: 'PURE WHITE' },
    { ja: '無限の', en: 'INFINITE' }, { ja: '最強の', en: 'STRONGEST' }, { ja: '最後の', en: 'LAST' },
    { ja: '不滅の', en: 'IMMORTAL' }, { ja: '不屈の', en: 'INDOMITABLE' }, { ja: '孤高の', en: 'SOLITARY' },
    { ja: '神速の', en: 'GODSPEED' }, { ja: '轟く', en: 'THUNDERING' }, { ja: '燃ゆる', en: 'BURNING' },
    { ja: '凍てつく', en: 'FROZEN' }, { ja: '渦巻く', en: 'SWIRLING' }, { ja: '目覚める', en: 'AWAKENING' },
    { ja: 'たのしい', en: 'JOYFUL' }, { ja: 'にぎやかな', en: 'LIVELY' }, { ja: 'のんびりした', en: 'LEISURELY' },
    { ja: 'ふしぎな', en: 'CURIOUS' }, { ja: 'ゆかいな', en: 'MERRY' }, { ja: 'あたらしい', en: 'BRAND NEW' }
  ],
  systemWord: [
    'オープンワールド', 'ターン制コマンドバトル', 'リアルタイムストラテジー', 'ローグライク',
    'ソウルライク', 'ハック＆スラッシュ', '拠点構築', 'マルチエンディング', '4人協力プレイ',
    '非対称対戦', 'クラフト＆サバイバル', '会話選択分岐', 'シームレスフィールド',
    '陣取り戦略', 'カードバトル', '探索アクション', '街づくり', '対戦格闘',
    'リズムアクション', 'パズルアクション', '推理アドベンチャー', '育成シミュレーション',
    '経営シミュレーション', '恋愛アドベンチャー', 'ノベルゲーム', 'タワーディフェンス',
    'デッキ構築', 'ローグライト', 'メトロイドヴァニア', 'ステルスアクション',
    'サンドボックス', '一人称視点シューティング', '見下ろし型アクション', '横スクロールアクション',
    '協力プレイ対応', 'オンライン対戦', '非同期対戦', 'リプレイ共有', 'ステージ作成',
    '自由編成バトル', 'ジョブチェンジ', 'スキルツリー', '装備錬成', '素材採取',
    '釣り要素', '料理要素', '農業要素', '牧場経営', '鉄道敷設', '交通整備',
    '住民交流', '季節変化', '天候変化', '昼夜サイクル', '難易度選択', '実績収集'
  ],
  platform: [
    'NEXUS-7', 'ORBIT STATION', 'HEXA DRIVE', 'PULSE BOX', 'ZENITH-X',
    'CIRCA 88', 'VOID DECK', 'AURA PORTABLE', 'GRID CONSOLE',
    'ECHO STATION', 'TERRA BOX', 'HELIX 9', 'PRISM DECK', 'NOVA PORTABLE',
    'LUMEN CUBE', 'QUANTA PAD', 'VECTOR ONE', 'SOLARIS', 'MERIDIAN GO',
    'ATLAS STATION', 'CORTEX BOX', 'DELTA DECK', 'EMBER PORTABLE', 'FLUX CONSOLE',
    'GEMINI TWO', 'HALCYON', 'IRIS HANDHELD', 'JUNO STATION', 'KRYPTON X',
    'LATTICE', 'MOSAIC BOX', 'NIMBUS PAD', 'OCTAVE DECK', 'PARADIGM',
    'QUASAR ONE', 'RIFT STATION', 'SPECTRA GO', 'TESSERA', 'ULTRA DECK',
    'VERTEX BOX', 'WAVELENGTH', 'XENON PAD', 'YIELD CONSOLE', 'ZEPHYR PORTABLE'
  ],
  editionWord: [
    'DELUXE EDITION', 'COMPLETE EDITION', 'ANNIVERSARY EDITION', 'ULTIMATE EDITION',
    'GOLD EDITION', "COLLECTOR'S BOX", 'REMASTERED', 'DEFINITIVE EDITION',
    'SEASON PASS 同梱', '早期購入特典付',
    'PREMIUM BOX', '完全生産限定版', 'TRILOGY PACK', '設定資料集同梱版', 'ANNIVERSARY BOX',
    'STARTER PACK', 'DOUBLE PACK', 'TWIN PACK', 'BEST 版', '廉価版',
    'HD REMASTER', '4K EDITION', 'DIRECTOR MODE 収録', '追加シナリオ同梱',
    'サウンドトラック同梱', 'アートブック同梱', 'フィギュア同梱', '特製ケース仕様',
    'ダウンロードコード同梱', '初回生産限定版', '通常版', 'パッケージ版限定',
    'SPECIAL EDITION', 'LEGACY EDITION', 'ETERNAL EDITION', 'PLATINUM EDITION',
    'ARCHIVE EDITION', 'MEMORIAL BOX', 'FAN BOX', 'ORIGIN COLLECTION'
  ],
  publisherName: [
    '群青ゲームス', 'ヘキサソフト', 'オービットワークス', 'ゼニス・インタラクティブ',
    '蒼波スタジオ', 'VOID WORKS', 'パルスゲームズ', 'アウラ・エンタテインメント',
    '内海インタラクティブ', 'HELIX SOFT', '黒森ゲームズ', 'テラワークス', '白夜エンタテインメント',
    'PRISM SOFT', '汐見ゲームス', 'NOVA INTERACTIVE', '海鳴ソフト', 'LUMEN GAMES',
    '氷河スタジオ', 'QUANTA SOFT', '砂丘ゲームズ', 'VECTOR WORKS', '灯台エンタテインメント',
    'SOLARIS SOFT', '青嵐ゲームス', 'MERIDIAN GAMES', '夜航スタジオ', 'ATLAS SOFT',
    '極東インタラクティブ', 'CORTEX GAMES', '白鯨ソフト', 'DELTA WORKS', '銀河エンタテインメント',
    'EMBER SOFT', '無限ゲームス', 'FLUX INTERACTIVE', '暁光スタジオ', 'GEMINI GAMES',
    '残照ソフト', 'HALCYON WORKS', '朔北ゲームス', 'IRIS SOFT', '西海インタラクティブ',
    'JUNO GAMES', '東雲スタジオ', 'KRYPTON SOFT', '曙エンタテインメント', 'LATTICE GAMES'
  ],
  ratingWord: [
    'CERO A　全年齢対象', 'CERO B　12才以上対象', 'CERO C　15才以上対象',
    'CERO D　17才以上対象', 'CERO Z　18才以上のみ対象'
  ]
});

})(window.PF = window.PF || {});
