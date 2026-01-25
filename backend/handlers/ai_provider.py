"""AI Provider API - AIプロバイダーの管理とチャットAPI"""
import time
from flask import Flask,jsonify,request,Response
from providers import get_provider,list_providers,AIProviderConfig
from providers.base import ChatMessage,MessageRole
from providers.registry import register_all_providers
from providers.health_monitor import get_health_monitor


def register_ai_provider_routes(app:Flask):
 """Register AI provider related routes"""

 register_all_providers()

 @app.route('/api/ai-providers',methods=['GET'])
 def get_ai_providers():
  """Get list of available AI providers"""
  providers=list_providers()
  return jsonify(providers)

 @app.route('/api/ai-providers/<provider_id>',methods=['GET'])
 def get_ai_provider(provider_id:str):
  """Get specific AI provider details"""
  provider=get_provider(provider_id)
  if not provider:
   return jsonify({"error":f"プロバイダーが見つかりません: {provider_id}"}),404

  models=[
   {
    "id":m.id,
    "name":m.name,
    "maxTokens":m.max_tokens,
    "supportsVision":m.supports_vision,
    "supportsTools":m.supports_tools,
    "inputCostPer1k":m.input_cost_per_1k,
    "outputCostPer1k":m.output_cost_per_1k,
   }
   for m in provider.get_available_models()
  ]

  return jsonify({
   "id":provider.provider_id,
   "name":provider.display_name,
   "models":models
  })

 @app.route('/api/ai-providers/<provider_id>/models',methods=['GET'])
 def get_ai_provider_models(provider_id:str):
  """Get available models for a provider"""
  provider=get_provider(provider_id)
  if not provider:
   return jsonify({"error":f"プロバイダーが見つかりません: {provider_id}"}),404

  models=[
   {
    "id":m.id,
    "name":m.name,
    "maxTokens":m.max_tokens,
    "supportsVision":m.supports_vision,
    "supportsTools":m.supports_tools,
    "inputCostPer1k":m.input_cost_per_1k,
    "outputCostPer1k":m.output_cost_per_1k,
   }
   for m in provider.get_available_models()
  ]

  return jsonify(models)

 @app.route('/api/ai-providers/test',methods=['POST'])
 def test_ai_provider():
  """Test connection to an AI provider"""
  data=request.get_json()

  if not data:
   return jsonify({"error":"Request body is required"}),400

  provider_type=data.get('providerType','')
  config_data=data.get('config',{})

  if not provider_type:
   return jsonify({"error":"providerType is required"}),400

  start_time=time.time()

  try:
   config=AIProviderConfig(
    api_key=config_data.get('apiKey'),
    base_url=config_data.get('baseUrl'),
   )
   provider=get_provider(provider_type,config)

   if not provider:
    return jsonify({
     "success":False,
     "message":f"未対応のプロバイダー: {provider_type}"
    }),400

   result=provider.test_connection()
   latency=int((time.time()-start_time)*1000)
   result["latency"]=latency

   return jsonify(result)

  except Exception as e:
   latency=int((time.time()-start_time)*1000)
   return jsonify({
    "success":False,
    "message":f"接続エラー: {str(e)}",
    "latency":latency
   })

 @app.route('/api/ai/chat',methods=['POST'])
 def ai_chat():
  """Chat completion API"""
  data=request.get_json()

  if not data:
   return jsonify({"error":"Request body is required"}),400

  provider_id=data.get('provider','anthropic')
  model=data.get('model')
  messages_data=data.get('messages',[])
  max_tokens=data.get('maxTokens',1024)
  temperature=data.get('temperature',0.7)
  api_key=data.get('apiKey')

  if not messages_data:
   return jsonify({"error":"messages is required"}),400

  config=AIProviderConfig(api_key=api_key) if api_key else None
  provider=get_provider(provider_id,config)

  if not provider:
   return jsonify({"error":f"未対応のプロバイダー: {provider_id}"}),400

  if not model:
   model=provider.get_default_model()

  messages=[]
  for msg in messages_data:
   role_str=msg.get('role','user')
   try:
    role=MessageRole(role_str)
   except ValueError:
    role=MessageRole.USER
   messages.append(ChatMessage(role=role,content=msg.get('content','')))

  try:
   start_time=time.time()
   response=provider.chat(
    messages=messages,
    model=model,
    max_tokens=max_tokens,
    temperature=temperature
   )
   latency=int((time.time()-start_time)*1000)

   return jsonify({
    "content":response.content,
    "model":response.model,
    "usage":{
     "inputTokens":response.input_tokens,
     "outputTokens":response.output_tokens,
     "totalTokens":response.total_tokens
    },
    "finishReason":response.finish_reason,
    "latency":latency
   })

  except Exception as e:
   return jsonify({"error":f"チャットエラー: {str(e)}"}),500

 @app.route('/api/ai/chat/stream',methods=['POST'])
 def ai_chat_stream():
  """Streaming chat completion API"""
  data=request.get_json()

  if not data:
   return jsonify({"error":"Request body is required"}),400

  provider_id=data.get('provider','anthropic')
  model=data.get('model')
  messages_data=data.get('messages',[])
  max_tokens=data.get('maxTokens',1024)
  temperature=data.get('temperature',0.7)
  api_key=data.get('apiKey')

  if not messages_data:
   return jsonify({"error":"messages is required"}),400

  config=AIProviderConfig(api_key=api_key) if api_key else None
  provider=get_provider(provider_id,config)

  if not provider:
   return jsonify({"error":f"未対応のプロバイダー: {provider_id}"}),400

  if not model:
   model=provider.get_default_model()

  messages=[]
  for msg in messages_data:
   role_str=msg.get('role','user')
   try:
    role=MessageRole(role_str)
   except ValueError:
    role=MessageRole.USER
   messages.append(ChatMessage(role=role,content=msg.get('content','')))

  def generate():
   try:
    import json
    for chunk in provider.chat_stream(
     messages=messages,
     model=model,
     max_tokens=max_tokens,
     temperature=temperature
    ):
     if chunk.is_final:
      yield f"data: {json.dumps({'done':True,'usage':{'inputTokens':chunk.input_tokens,'outputTokens':chunk.output_tokens}})}\n\n"
     else:
      yield f"data: {json.dumps({'content':chunk.content})}\n\n"
   except Exception as e:
    import json
    yield f"data: {json.dumps({'error':str(e)})}\n\n"

  return Response(
   generate(),
   mimetype='text/event-stream',
   headers={
    'Cache-Control':'no-cache',
    'X-Accel-Buffering':'no'
   }
  )

 @app.route('/api/providers/health',methods=['GET'])
 def get_providers_health():
  """全プロバイダーのヘルス状態を取得"""
  monitor=get_health_monitor()
  return jsonify(monitor.get_all_health_status())

 @app.route('/api/providers/<provider_id>/health',methods=['GET'])
 def get_provider_health(provider_id:str):
  """特定プロバイダーのヘルスチェックを実行"""
  monitor=get_health_monitor()
  result=monitor.check_provider_now(provider_id)
  return jsonify(result.to_dict())

 @app.route('/api/api-keys',methods=['GET'])
 def get_api_keys():
  """保存済みAPIキー一覧（ヒントのみ）"""
  from models.database import get_session
  from repositories import ApiKeyRepository
  session=get_session()
  try:
   repo=ApiKeyRepository(session)
   hints=repo.get_all_hints()
   return jsonify(hints)
  finally:
   session.close()

 @app.route('/api/api-keys/<provider_id>',methods=['PUT'])
 def save_api_key(provider_id:str):
  """APIキーを保存"""
  from models.database import get_session
  from repositories import ApiKeyRepository
  data=request.get_json()
  if not data or not data.get('apiKey'):
   return jsonify({"error":"apiKeyは必須です"}),400
  api_key=data['apiKey']
  session=get_session()
  try:
   repo=ApiKeyRepository(session)
   key_store=repo.save(provider_id,api_key)
   session.commit()
   return jsonify({
    "success":True,
    "hint":key_store.key_hint,
    "message":"APIキーが保存されました"
   })
  except Exception as e:
   session.rollback()
   return jsonify({"error":str(e)}),500
  finally:
   session.close()

 @app.route('/api/api-keys/<provider_id>',methods=['DELETE'])
 def delete_api_key(provider_id:str):
  """APIキーを削除"""
  from models.database import get_session
  from repositories import ApiKeyRepository
  session=get_session()
  try:
   repo=ApiKeyRepository(session)
   deleted=repo.delete(provider_id)
   session.commit()
   if deleted:
    return jsonify({"success":True,"message":"APIキーが削除されました"})
   else:
    return jsonify({"error":"APIキーが見つかりません"}),404
  except Exception as e:
   session.rollback()
   return jsonify({"error":str(e)}),500
  finally:
   session.close()

 @app.route('/api/api-keys/<provider_id>/validate',methods=['POST'])
 def validate_api_key(provider_id:str):
  """APIキーの有効性を検証"""
  from models.database import get_session
  from repositories import ApiKeyRepository
  session=get_session()
  try:
   repo=ApiKeyRepository(session)
   api_key=repo.get_decrypted_key(provider_id)
   if not api_key:
    return jsonify({"success":False,"error":"APIキーが保存されていません"}),404
   config=AIProviderConfig(api_key=api_key)
   provider=get_provider(provider_id,config)
   if not provider:
    return jsonify({"success":False,"error":"未対応のプロバイダーです"}),400
   start_time=time.time()
   result=provider.test_connection()
   latency=int((time.time()-start_time)*1000)
   is_valid=result.get("success",False)
   repo.update_validation_status(provider_id,is_valid)
   session.commit()
   return jsonify({
    "success":is_valid,
    "message":result.get("message",""),
    "latency":latency
   })
  except Exception as e:
   session.rollback()
   return jsonify({"success":False,"error":str(e)}),500
  finally:
   session.close()
