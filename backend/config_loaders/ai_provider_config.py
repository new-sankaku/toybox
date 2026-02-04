from typing import Dict,Any,Optional,List
from config_loaders import load_yaml_config


def get_ai_providers_config()->Dict[str,Any]:
    return load_yaml_config("ai_providers.yaml")


def get_pricing_config()->Dict[str,Any]:
    config=get_ai_providers_config()
    currency=config.get("pricing",{}).get("currency","USD")
    units=config.get("pricing",{}).get("units",{})
    models={}
    for provider_id,provider in config.get("providers",{}).items():
        for model in provider.get("models",[]):
            models[model["id"]]={
                "provider":provider_id,
                "pricing":model.get("pricing",{})
            }
    return {"currency":currency,"units":units,"models":models}


def get_provider_config(provider_id:str)->Dict[str,Any]:
    config=get_ai_providers_config()
    providers=config.get("providers",{})
    return providers.get(provider_id,{})


def get_provider_env_key(provider_id:str)->str:
    provider=get_provider_config(provider_id)
    return provider.get("env_key","")


def get_provider_models(provider_id:str)->List[Dict[str,Any]]:
    provider=get_provider_config(provider_id)
    return provider.get("models",[])


def get_provider_test_model(provider_id:str)->str:
    provider=get_provider_config(provider_id)
    test_model=provider.get("test_model")
    if test_model:
        return test_model
    models=provider.get("models",[])
    if models:
        return models[0].get("id","")
    return""


def get_provider_default_model(provider_id:str)->str:
    config=get_ai_providers_config()
    for cat in config.get("usage_categories",[]):
        default=cat.get("default",{})
        if default.get("provider")==provider_id:
            return default.get("model","")
    provider=get_provider_config(provider_id)
    models=provider.get("models",[])
    if models:
        recommended=[m for m in models if m.get("recommended")]
        if recommended:
            return recommended[0].get("id","")
        return models[0].get("id","")
    return""


def get_provider_max_concurrent(provider_id:str)->int:
    provider=get_provider_config(provider_id)
    return provider.get("max_concurrent",3)


def get_provider_group(provider_id:str)->Optional[str]:
    provider=get_provider_config(provider_id)
    return provider.get("group")


def get_group_max_concurrent(group_id:str)->int:
    config=get_ai_providers_config()
    groups=config.get("provider_groups",{})
    group=groups.get(group_id,{})
    return group.get("max_concurrent",5)


def get_service_types()->List[str]:
    return get_ai_providers_config().get('service_types',[])


def get_service_labels()->Dict[str,str]:
    return get_ai_providers_config().get('service_labels',{})


def get_provider_type_mapping()->Dict[str,str]:
    return get_ai_providers_config().get('provider_type_mapping',{})


def get_reverse_provider_type_mapping()->Dict[str,str]:
    mapping=get_provider_type_mapping()
    return {v:k for k,v in mapping.items()}


def get_defaults()->Dict[str,Dict[str,str]]:
    result={}
    for cat in get_usage_categories():
        stype=cat.get('service_type','')
        if stype and stype not in result:
            d=cat.get('default',{})
            result[stype]={'provider':d.get('provider',''),'model':d.get('model','')}
    return result


def get_providers()->Dict[str,Dict[str,Any]]:
    return get_ai_providers_config().get('providers',{})


def get_usage_categories()->List[Dict[str,Any]]:
    return get_ai_providers_config().get('usage_categories',[])


def get_providers_for_service(service_type:str)->List[Dict[str,Any]]:
    result=[]
    for provider_id,provider in get_providers().items():
        if service_type in provider.get('service_types',[]):
            result.append({
                'id':provider_id,
                'label':provider['label'],
                'models':provider.get('models',[]),
                'defaultModel':provider.get('default_model','')
            })
    return result


def build_default_ai_services()->Dict[str,Dict[str,Any]]:
    result={}
    defaults=get_defaults()
    for stype in get_service_types():
        d=defaults.get(stype,{})
        result[stype]={
            "enabled":True,
            "provider":d.get("provider",""),
            "model":d.get("model","")
        }
    return result


def get_ai_pricing_config()->Dict[str,Any]:
    return get_ai_providers_config().get('pricing',{})


def get_model_pricing(provider_id:str,model_id:str)->Optional[Dict[str,Any]]:
    providers=get_providers()
    provider=providers.get(provider_id)
    if not provider:
        return None
    models=provider.get('models',[])
    for m in models:
        if m.get('id')==model_id:
            return m.get('pricing')
    return None


def get_all_model_pricing()->Dict[str,Dict[str,Any]]:
    result={}
    for pid,pdata in get_providers().items():
        for m in pdata.get('models',[]):
            mid=m.get('id','')
            pricing=m.get('pricing')
            if pricing:
                result[mid]={
                    'provider':pid,
                    'pricing':pricing
                }
    return result
