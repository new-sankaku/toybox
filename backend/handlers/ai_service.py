
"""AI Service API - AIサービスタイプの設定を提供"""
from flask import Flask,jsonify
from ai_config import (
 get_service_types,
 get_service_labels,
 get_defaults,
 get_providers,
 get_providers_for_service,
 get_pricing_config,
 get_all_model_pricing,
 get_usage_categories
)


def register_ai_service_routes(app:Flask):

 @app.route('/api/ai-services',methods=['GET'])
 def get_ai_services():
  result = {}
  defaults = get_defaults()
  providers = get_providers()
  labels = get_service_labels()
  for service_type in get_service_types():
   default = defaults.get(service_type,{})
   provider_id = default.get('provider','')
   provider = providers.get(provider_id,{})
   result[service_type] = {
    'label':labels.get(service_type,service_type),
    'description':provider.get('label',''),
    'provider':provider_id,
    'model':default.get('model','')
   }
  return jsonify(result)

 @app.route('/api/ai-services/<service_type>',methods=['GET'])
 def get_ai_service(service_type:str):
  if service_type not in get_service_types():
   return jsonify({'error':f'サービスが見つかりません: {service_type}'}),404
  defaults = get_defaults()
  providers = get_providers()
  labels = get_service_labels()
  default = defaults.get(service_type,{})
  provider_id = default.get('provider','')
  provider = providers.get(provider_id,{})
  return jsonify({
   'label':labels.get(service_type,service_type),
   'description':provider.get('label',''),
   'provider':provider_id,
   'model':default.get('model','')
  })

 @app.route('/api/config/ai-services',methods=['GET'])
 def get_ai_services_master():
  services = {}
  labels = get_service_labels()
  defaults = get_defaults()
  for service_type in get_service_types():
   services[service_type] = {
    'label':labels.get(service_type,service_type),
    'providers':get_providers_for_service(service_type),
    'default':defaults.get(service_type,{})
   }
  providers_raw = get_providers()
  providers_out = {}
  for pid,pdata in providers_raw.items():
   providers_out[pid] = {
    'label':pdata.get('label',''),
    'serviceTypes':pdata.get('service_types',[]),
    'models':pdata.get('models',[]),
    'defaultModel':pdata.get('default_model','')
   }
   if 'samplers' in pdata:
    providers_out[pid]['samplers'] = pdata['samplers']
   if 'schedulers' in pdata:
    providers_out[pid]['schedulers'] = pdata['schedulers']
  return jsonify({
   'serviceTypes':get_service_types(),
   'usageCategories':get_usage_categories(),
   'services':services,
   'providers':providers_out
  })

 @app.route('/api/config/ai-providers',methods=['GET'])
 def get_ai_providers_master():
  providers_raw = get_providers()
  providers_out = {}
  for pid,pdata in providers_raw.items():
   providers_out[pid] = {
    'label':pdata.get('label',''),
    'serviceTypes':pdata.get('service_types',[]),
    'models':pdata.get('models',[]),
    'defaultModel':pdata.get('default_model','')
   }
   if 'samplers' in pdata:
    providers_out[pid]['samplers'] = pdata['samplers']
   if 'schedulers' in pdata:
    providers_out[pid]['schedulers'] = pdata['schedulers']
  return jsonify(providers_out)

 @app.route('/api/config/pricing',methods=['GET'])
 def get_pricing():
  pricing_config = get_pricing_config()
  model_pricing = get_all_model_pricing()
  return jsonify({
   'currency':pricing_config.get('currency','USD'),
   'units':pricing_config.get('units',{}),
   'models':model_pricing
  })
