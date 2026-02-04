from typing import Dict,Any,Optional,Set,List
from config_loaders import load_yaml_config


def get_agents_config()->Dict[str,Any]:
    return load_yaml_config("agents.yaml")


def get_agent_definitions_config()->Dict[str,Any]:
    config=get_agents_config()
    agents=config.get("agents",{})
    agents_out={}
    for agent_id,agent in agents.items():
        agents_out[agent_id]={
            "label":agent.get("label",""),
            "shortLabel":agent.get("short_label",""),
            "phase":agent.get("phase",0),
            "speechBubble":agent.get("speech_bubble",""),
        }
    high_cost_agents=[k for k,v in agents.items() if v.get("high_cost",False)]
    quality_defaults=config.get("quality_check_defaults",{"max_retries":3})
    phases={}
    for phase_id,phase in config.get("phases",{}).items():
        phases[phase_id]=phase.get("agents",[])
    display_names={k:v.get("label","") for k,v in agents.items()}
    return {
        "agents":agents_out,
        "highCostAgents":high_cost_agents,
        "qualityCheckDefaults":{"enabled":True,"maxRetries":quality_defaults.get("max_retries",3)},
        "phases":phases,
        "displayNames":display_names,
    }


def get_agent_definitions()->Dict[str,Dict[str,Any]]:
    config=get_agent_definitions_config()
    return config.get("agents",{})


def get_high_cost_agents()->Set[str]:
    config=get_agent_definitions_config()
    return set(config.get("highCostAgents",[]))


def get_agent_phases()->Dict[str,List[str]]:
    config=get_agent_definitions_config()
    return config.get("phases",{})


def get_agent_display_names()->Dict[str,str]:
    config=get_agent_definitions_config()
    return config.get("displayNames",{})


def get_quality_check_defaults()->Dict[str,Any]:
    config=get_agent_definitions_config()
    return config.get("qualityCheckDefaults",{"enabled":True,"maxRetries":3})


def get_agent_definitions_from_yaml()->Dict[str,Dict[str,Any]]:
    config=get_agents_config()
    agents=config.get("agents",{})
    result={}
    for agent_id,agent in agents.items():
        result[agent_id]={
            "label":agent.get("label",""),
            "shortLabel":agent.get("short_label",""),
            "phase":agent.get("phase",0),
            "speechBubble":agent.get("speech_bubble",""),
        }
    return result


def get_high_cost_agents_from_yaml()->Set[str]:
    config=get_agents_config()
    agents=config.get("agents",{})
    return {k for k,v in agents.items() if v.get("high_cost",False)}


def get_quality_check_defaults_from_yaml()->Dict[str,bool]:
    config=get_agents_config()
    agents=config.get("agents",{})
    return {k:v.get("quality_check",True) for k,v in agents.items()}


def get_agent_phases_from_yaml()->Dict[str,List[str]]:
    config=get_agents_config()
    phases=config.get("phases",{})
    result={}
    for phase_id,phase in phases.items():
        result[phase_id]=phase.get("agents",[])
    return result


def get_agent_display_names_from_yaml()->Dict[str,str]:
    config=get_agents_config()
    agents=config.get("agents",{})
    return {k:v.get("label","") for k,v in agents.items()}


def get_ui_phases()->List[Dict[str,Any]]:
    config=get_agents_config()
    return config.get("ui_phases",[])


def get_agent_asset_mapping()->Dict[str,List[str]]:
    config=get_agents_config()
    return config.get("agent_asset_mapping",{})


def get_agent_service_map()->Dict[str,str]:
    config=get_agents_config()
    agents=config.get("agents",{})
    return {k:v.get("output_type","llm") for k,v in agents.items()}


def get_agent_types()->List[str]:
    return list(get_agents_config().get("agents",{}).keys())


def get_agent_max_tokens(agent_type:str)->Optional[int]:
    config=get_agents_config()
    agents=config.get("agents",{})
    agent=agents.get(agent_type,{})
    return agent.get("max_tokens")


def get_agent_temperature(agent_type:str)->float:
    config=get_agents_config()
    agents=config.get("agents",{})
    agent=agents.get(agent_type,{})
    if"temperature" in agent:
        return float(agent["temperature"])
    role=agent.get("role","default")
    temp_defaults=config.get("temperature_defaults",{})
    return float(temp_defaults.get(role,temp_defaults.get("default",0.7)))


def get_temperature_defaults()->Dict[str,float]:
    config=get_agents_config()
    return config.get("temperature_defaults",{
        "leader":0.7,
        "worker":0.5,
        "splitter":0.3,
        "integrator":0.4,
        "tester":0.3,
        "default":0.7
    })


def get_agent_roles()->Dict[str,str]:
    config=get_agents_config()
    agents=config.get("agents",{})
    return {k:v.get("role","worker") for k,v in agents.items()}


def get_agent_usage_category(agent_type:str)->str:
    config=get_agents_config()
    agents=config.get("agents",{})
    agent=agents.get(agent_type,{})
    return agent.get("usage_category","llm_mid")


def get_generation_type_for_agent(agent_type:str)->str:
    config=get_agents_config()
    gen_types=config.get("agent_generation_types",{})
    for gen_type,agents in gen_types.items():
        if agent_type in agents:
            return gen_type
    return"llm"


def get_agent_assets(agent_type:str)->List[Dict[str,Any]]:
    config=get_agents_config()
    assets=config.get("agent_assets",{})
    return assets.get(agent_type,[])


def get_agent_checkpoints(agent_type:str)->List[Dict[str,Any]]:
    config=get_agents_config()
    checkpoints=config.get("agent_checkpoints",{})
    return checkpoints.get(agent_type,[])


def get_output_requirements(agent_type:str)->Dict[str,Any]:
    config=get_agents_config()
    reqs=config.get("output_requirements",{})
    return reqs.get(agent_type,reqs.get("_default",{"min_length":200}))


def get_advanced_quality_check_settings()->Dict[str,Any]:
    config=get_agents_config()
    return config.get("advanced_quality_check",{
        "quality_threshold":0.6,
        "escalation":{
            "enabled":True,
            "tier2_score_min":0.5,
            "tier2_score_max":0.7
        }
    })


def get_tool_execution_limits()->Dict[str,Any]:
    config=get_agents_config()
    return config.get("tool_execution_limits",{
        "max_iterations":50,
        "timeout_seconds":300,
        "loop_detection_threshold":3
    })


def get_generation_metrics_config()->Dict[str,Any]:
    config=get_agents_config()
    return config.get("generation_metrics",{})


def get_generation_metrics_categories()->Dict[str,Dict[str,str]]:
    metrics=get_generation_metrics_config()
    return metrics.get("categories",{})


def get_agent_generation_metrics(agent_type:str)->Optional[Dict[str,Any]]:
    metrics=get_generation_metrics_config()
    agent_metrics=metrics.get("agent_metrics",{})
    return agent_metrics.get(agent_type)
