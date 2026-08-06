"""Benchmark結果のReport出力

判断に必要な指標だけを上段に置き、詳細はJSON側へ委ねる。
"""
import json
from pathlib import Path
from typing import Dict,List

_NA="-"


def _format(value,digits:int=3)->str:
 if value is None:
  return _NA
 if isinstance(value,float) and value!=value:
  return _NA
 if isinstance(value,float):
  return f"{value:.{digits}f}"
 return str(value)


def _summary_row(name:str,summary:Dict)->str:
 return "|".join([
  "",
  name,
  _format(summary["roc_auc"]),
  _format(summary["eer"]),
  _format(summary["false_reject_rate_at_target_far"]),
  _format(summary["lm_correction_rate"]),
  _format(summary["localization_accuracy"]),
  _format(summary["latency_ms"].get("p50"),1),
  _format(summary["latency_ms"].get("p95"),1),
  _format(summary["real_time_factor"].get("p95")),
  "",
 ])


def render_markdown(result:Dict)->str:
 """Benchmark結果をMarkdownへ整形する"""
 metrics_config=result["metrics_config"]
 lines:List[str]=[]
 lines.append("# Hayakuchi 判定Engine Benchmark")
 lines.append("")
 lines.append(f"- 実行日時: {result['generated_at']}")
 lines.append(f"- Manifest: {result['manifest']}")
 lines.append(f"- Sample数: {result['sample_count']}")
 lines.append(f"- 目標FAR: {metrics_config['target_far']}")
 lines.append(f"- 誤り位置許容Mora数: {metrics_config['localization_tolerance']}")
 lines.append("")
 lines.append("## 総合")
 lines.append("")
 header="|Engine|AUC|EER|FRR@FAR|LM補正率|誤り位置精度|遅延p50(ms)|遅延p95(ms)|RTF p95|"
 divider="|---|---|---|---|---|---|---|---|---|"
 lines.append(header)
 lines.append(divider)
 for engine in result["engines"]:
  lines.append(_summary_row(engine["engine_id"],engine["overall"]))
 lines.append("")
 lines.append("## 条件別")
 lines.append("")
 for engine in result["engines"]:
  lines.append(f"### {engine['engine_id']} ({engine['adapter']})")
  lines.append("")
  lines.append(f"- Model読み込み: {engine['load_ms']:.1f}ms")
  lines.append("")
  lines.append(header.replace("|Engine|","|Condition|",1))
  lines.append(divider)
  for entry in engine["conditions"]:
   lines.append(_summary_row(entry["condition_label"],entry["summary"]))
  lines.append("")
 lines.append("## 指標の読み方")
 lines.append("")
 lines.append("- AUCとEERは判定Scoreの分離性能。EERが低いほど閾値設計が楽になる")
 lines.append("- FRR@FARは、噛みの見逃しを目標値に抑えたときに正解を誤ってFAILにする率。配信体験への影響が最も大きい")
 lines.append("- LM補正率は、噛んだ音声をEngineが正解文へ書き換えた率。高いEngineは本用途では採用不可")
 lines.append("- RTFが1.0を超えるEngineはReal timeで追従できない")
 lines.append("")
 return "\n".join(lines)


def write_report(result:Dict,output_dir:Path,stem:str)->Dict[str,Path]:
 """JSONとMarkdownの両方を書き出す"""
 output_dir.mkdir(parents=True,exist_ok=True)
 json_path=output_dir/f"{stem}.json"
 markdown_path=output_dir/f"{stem}.md"
 with json_path.open("w",encoding="utf-8") as handle:
  json.dump(result,handle,ensure_ascii=False,indent=2)
 with markdown_path.open("w",encoding="utf-8") as handle:
  handle.write(render_markdown(result))
 return {"json":json_path,"markdown":markdown_path}
