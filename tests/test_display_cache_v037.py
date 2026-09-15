import numpy as np
import pandas as pd

from runlab.display_cache import DisplaySeriesCache
from runlab.models import TelemetryRun, TimingData


def _run():
    t = np.arange(0.0, 5.0, 0.01)
    frame = pd.DataFrame({"Time": t, "RPM": 5000.0 + 1000.0 * t})
    return TelemetryRun(
        name="cache-test",
        data=frame,
        units={"Time": "s", "RPM": "rpm"},
        channel_map={"time_s": "Time", "engine_rpm": "RPM"},
        timing=TimingData(quarter_mile_s=4.0),
        metadata={"original_channel_map": {"time_s": "Time", "engine_rpm": "RPM"}},
    )


def test_xy_mapping_is_cached():
    run = _run()
    cache = DisplaySeriesCache()
    x1, y1 = cache.xy(run, "RPM", "Logger Time")
    x2, y2 = cache.xy(run, "RPM", "Logger Time")
    assert x1 is x2
    assert y1 is y2
    stats = cache.stats()
    assert stats.xy_misses == 1
    assert stats.xy_hits == 1


def test_sample_many_matches_linear_interpolation():
    run = _run()
    cache = DisplaySeriesCache()
    values = cache.sample_many(run, "RPM", [0.0, 1.25, 4.99, 6.0], "Logger Time")
    assert np.allclose(values[:3], [5000.0, 6250.0, 9990.0])
    assert np.isnan(values[3])


def test_snap_nearest_uses_sorted_grid():
    run = _run()
    cache = DisplaySeriesCache()
    grid = cache.snap_grid(run, "RPM", "Logger Time")
    assert cache.nearest(grid, 1.234) == 1.23
    assert cache.nearest(grid, 1.236) == 1.24


def test_nonmonotonic_duplicate_x_is_prepared_once():
    run = _run()
    run.data = pd.DataFrame({"Time": [0.0, 1.0, 1.0, 0.5, 2.0], "RPM": [1.0, 2.0, 3.0, 4.0, 5.0]})
    cache = DisplaySeriesCache()
    xx, yy = cache.interpolation_view(run, "RPM", "Logger Time")
    assert np.all(np.diff(xx) > 0)
    assert len(xx) == len(yy)
    a = cache.stats()
    cache.interpolation_view(run, "RPM", "Logger Time")
    b = cache.stats()
    assert b.interpolation_hits == a.interpolation_hits + 1


def test_region_summary_uses_cached_window_statistics():
    import pandas as pd
    import numpy as np
    from runlab.models import TelemetryRun
    from runlab.display_cache import DisplaySeriesCache
    run=TelemetryRun('x',pd.DataFrame({'Time':[0,1,2,3,4],'RPM':[10,20,30,40,50]}),{'time_s':'Time','engine_rpm':'RPM'},units={'Time':'s','RPM':'rpm'})
    run.metadata['original_channel_map']=dict(run.channel_map)
    cache=DisplaySeriesCache()
    out=cache.region_summary(run,'RPM',1,3,'Logger Time',0)
    assert out['min']==20 and out['max']==40 and out['mean']==30 and out['count']==3
