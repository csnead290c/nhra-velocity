from __future__ import annotations

import numpy as np
import pandas as pd

from runlab.display_analysis import (
    channel_distribution,
    linear_regression,
    paired_channel_data,
    sample_channel_at,
)
from runlab.models import TelemetryRun, TimingData


def _run():
    t=np.linspace(0,10,101)
    x=np.linspace(0,20,101)
    y=3*x+2
    z=np.sin(t)
    df=pd.DataFrame({'Time':t,'X':x,'Y':y,'Z':z,'Gate':(x>5).astype(float),
                     '__time_s':t,'__x':x,'__y':y,'__z':z})
    return TelemetryRun(
        name='display', data=df,
        channel_map={'time_s':'__time_s','x':'__x','y':'__y','z':'__z'},
        units={'X':'psi','Y':'psi','Z':'g'},
        metadata={'original_channel_map':{'x':'X','y':'Y','z':'Z'}},
        timing=TimingData(quarter_mile_s=10.0),
    )


def test_paired_channels_and_regression():
    run=_run()
    data=paired_channel_data(run,'X','Y','Z')
    assert data.points==101
    fit=linear_regression(data.x,data.y)
    assert abs(fit.slope-3.0)<1e-10
    assert abs(fit.intercept-2.0)<1e-10
    assert fit.r_squared>0.999999


def test_gated_pair_does_not_hide_interpolation():
    run=_run()
    data=paired_channel_data(run,'X','Y',gate_expression='`Gate` > 0.5')
    assert data.points==75
    assert np.all(data.x>5)


def test_sample_and_percent_histogram():
    run=_run()
    snap=sample_channel_at(run,'X',5.0)
    assert snap.in_range
    assert abs(snap.value-10.0)<1e-9
    d=channel_distribution(run,'X',bins=10,mode='percent_samples')
    assert abs(float(np.sum(d.values))-100.0)<1e-9


def test_time_weighted_distribution_and_cumulative():
    run=_run()
    d=channel_distribution(run,'X',bins=10,mode='time',cumulative=False)
    assert abs(d.total_time_s-10.0)<1e-12
    assert abs(float(np.sum(d.values))-d.total_time_s)<1e-9
    c=channel_distribution(run,'X',bins=10,mode='percent_time',cumulative=True)
    assert abs(float(c.values[-1])-100.0)<1e-9
