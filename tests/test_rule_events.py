import numpy as np
import pandas as pd

from runlab.definition_library import DefinitionLibrary, EventRuleDefinition, ConstantDefinition
from runlab.rule_events import evaluate_event_rules, alarm_states_at
from runlab.models import TelemetryRun


def _run(name='RPM'):
    t=np.arange(0,5.01,.1); rpm=7000+700*t; throttle=np.where(t>=.5,100,0)
    r=TelemetryRun(name='test',data=pd.DataFrame({'Time':t,name:rpm,'TPS':throttle}),channel_map={'time_s':'Time','engine_rpm':name,'throttle_pct':'TPS'},units={'Time':'s',name:'rpm','TPS':'%'})
    r.metadata['original_channel_map']={'engine_rpm':name,'throttle_pct':'TPS'}
    return r


def test_rule_event_canonical_role_and_min_duration():
    lib=DefinitionLibrary();lib.constants['LIMIT']=ConstantDefinition('LIMIT',9000,'rpm');lib.event_rules['Limiter']=EventRuleDefinition('Limiter','engine_rpm >= LIMIT',severity='warning',min_duration_s=.2)
    f=evaluate_event_rules(lib,_run('Engine Speed'))
    assert len(f)==1 and f.iloc[0].severity=='warning' and f.iloc[0].duration_s>=.2


def test_rising_and_falling_edges():
    lib=DefinitionLibrary();lib.event_rules['WOT on']=EventRuleDefinition('WOT on','throttle_pct > 90',trigger='rising');lib.event_rules['WOT off']=EventRuleDefinition('WOT off','throttle_pct > 90',trigger='falling')
    f=evaluate_event_rules(lib,_run())
    assert set(f['trigger'])=={'rising','falling'} and all(f['duration_s']==0)


def test_alarm_state_uses_interval_rules():
    lib=DefinitionLibrary();lib.event_rules['High RPM']=EventRuleDefinition('High RPM','engine_rpm > 8500',trigger='interval')
    states=alarm_states_at(lib,_run(),3.0);assert states[0]['active']
    states=alarm_states_at(lib,_run(),1.0);assert not states[0]['active']


def test_event_rule_missing_channel_is_reported_by_library_validation():
    from runlab.definition_library import validate_library
    lib=DefinitionLibrary();lib.event_rules['Boost']=EventRuleDefinition('Boost','boost_psi > 10')
    check=validate_library(lib,_run());assert not check.valid and any('boost_psi' in x for x in check.missing)
