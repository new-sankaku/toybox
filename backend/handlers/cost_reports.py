from flask import Flask,request,jsonify,Response
from datetime import datetime
from datastore import get_session
from repositories.cost_history import CostHistoryRepository
from middleware.logger import get_logger
from middleware.error_handler import ApiError
import csv
import io
import json

def register_cost_reports_routes(app:Flask):

 @app.route('/api/cost/history',methods=['GET'])
 def get_cost_history():
  try:
   project_id=request.args.get('project_id')
   year=request.args.get('year',type=int)
   month=request.args.get('month',type=int)
   limit=request.args.get('limit',100,type=int)
   offset=request.args.get('offset',0,type=int)
   with get_session() as session:
    repo=CostHistoryRepository(session)
    if year and month:
     start=datetime(year,month,1)
     if month==12:
      end=datetime(year+1,1,1)
     else:
      end=datetime(year,month+1,1)
     entries=repo.get_by_date_range(start,end,project_id)
    elif project_id:
     entries=repo.get_by_project(project_id,limit=limit+offset)
    else:
     now=datetime.now()
     start=datetime(now.year,now.month,1)
     if now.month==12:
      end=datetime(now.year+1,1,1)
     else:
      end=datetime(now.year,now.month+1,1)
     entries=repo.get_by_date_range(start,end)
    paginated=entries[offset:offset+limit]
    return jsonify({
     "items":[{
      "id":e.id,
      "project_id":e.project_id,
      "agent_id":e.agent_id,
      "agent_type":e.agent_type,
      "service_type":e.service_type,
      "provider_id":e.provider_id,
      "model_id":e.model_id,
      "input_tokens":e.input_tokens,
      "output_tokens":e.output_tokens,
      "unit_count":e.unit_count,
      "cost_usd":float(e.cost_usd) if e.cost_usd else 0.0,
      "recorded_at":e.recorded_at.isoformat() if e.recorded_at else None,
      "metadata":e.metadata_
     } for e in paginated],
     "total":len(entries),
     "limit":limit,
     "offset":offset
    })
  except Exception as e:
   get_logger().error(f"Failed to get cost history: {e}",exc_info=True)
   raise ApiError("コスト履歴の取得に失敗しました",code="COST_HISTORY_ERROR",status_code=500)

 @app.route('/api/cost/summary',methods=['GET'])
 def get_cost_summary():
  try:
   year=request.args.get('year',type=int)
   month=request.args.get('month',type=int)
   now=datetime.now()
   if not year:
    year=now.year
   if not month:
    month=now.month
   with get_session() as session:
    repo=CostHistoryRepository(session)
    by_service=repo.get_summary_by_service(year,month)
    by_project=repo.get_summary_by_project(year,month)
    total=repo.get_monthly_total(year,month)
    return jsonify({
     "year":year,
     "month":month,
     "total_cost":round(total,4),
     "by_service":by_service,
     "by_project":by_project
    })
  except Exception as e:
   get_logger().error(f"Failed to get cost summary: {e}",exc_info=True)
   raise ApiError("コストサマリーの取得に失敗しました",code="COST_SUMMARY_ERROR",status_code=500)

 @app.route('/api/cost/export/csv',methods=['GET'])
 def export_cost_csv():
  try:
   year=request.args.get('year',type=int)
   month=request.args.get('month',type=int)
   project_id=request.args.get('project_id')
   now=datetime.now()
   if not year:
    year=now.year
   if not month:
    month=now.month
   with get_session() as session:
    repo=CostHistoryRepository(session)
    start=datetime(year,month,1)
    if month==12:
     end=datetime(year+1,1,1)
    else:
     end=datetime(year,month+1,1)
    entries=repo.get_by_date_range(start,end,project_id)
    output=io.StringIO()
    writer=csv.writer(output)
    writer.writerow(["ID","Project ID","Agent ID","Agent Type","Service Type","Provider","Model","Input Tokens","Output Tokens","Unit Count","Cost (USD)","Recorded At"])
    for e in entries:
     writer.writerow([
      e.id,e.project_id,e.agent_id or"",e.agent_type or"",e.service_type,
      e.provider_id or"",e.model_id or"",e.input_tokens,e.output_tokens,
      e.unit_count,e.cost_usd,e.recorded_at.isoformat() if e.recorded_at else""
     ])
    csv_content=output.getvalue()
    filename=f"cost_report_{year}_{month:02d}.csv"
    return Response(
     csv_content,
     mimetype="text/csv",
     headers={"Content-Disposition":f"attachment;filename={filename}"}
    )
  except Exception as e:
   get_logger().error(f"Failed to export CSV: {e}",exc_info=True)
   raise ApiError("CSVエクスポートに失敗しました",code="EXPORT_CSV_ERROR",status_code=500)

 @app.route('/api/cost/export/json',methods=['GET'])
 def export_cost_json():
  try:
   year=request.args.get('year',type=int)
   month=request.args.get('month',type=int)
   project_id=request.args.get('project_id')
   now=datetime.now()
   if not year:
    year=now.year
   if not month:
    month=now.month
   with get_session() as session:
    repo=CostHistoryRepository(session)
    start=datetime(year,month,1)
    if month==12:
     end=datetime(year+1,1,1)
    else:
     end=datetime(year,month+1,1)
    entries=repo.get_by_date_range(start,end,project_id)
    data={
     "export_date":datetime.now().isoformat(),
     "period":{"year":year,"month":month},
     "project_id":project_id,
     "items":[{
      "id":e.id,
      "project_id":e.project_id,
      "agent_id":e.agent_id,
      "agent_type":e.agent_type,
      "service_type":e.service_type,
      "provider_id":e.provider_id,
      "model_id":e.model_id,
      "input_tokens":e.input_tokens,
      "output_tokens":e.output_tokens,
      "unit_count":e.unit_count,
      "cost_usd":float(e.cost_usd) if e.cost_usd else 0.0,
      "recorded_at":e.recorded_at.isoformat() if e.recorded_at else None,
      "metadata":e.metadata_
     } for e in entries]
    }
    filename=f"cost_report_{year}_{month:02d}.json"
    return Response(
     json.dumps(data,ensure_ascii=False,indent=2),
     mimetype="application/json",
     headers={"Content-Disposition":f"attachment;filename={filename}"}
    )
  except Exception as e:
   get_logger().error(f"Failed to export JSON: {e}",exc_info=True)
   raise ApiError("JSONエクスポートに失敗しました",code="EXPORT_JSON_ERROR",status_code=500)
